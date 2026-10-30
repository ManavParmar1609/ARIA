"""Remove secrets and personal data from log text before it is stored or shown to an LLM.

Secrets are replaced outright. Identifiers that matter for triage (IP addresses, e-mail addresses)
are pseudonymised with a keyed hash: within one run ``10.0.0.7`` always becomes the same
``ip-3fa2c1d0``, even across parallel shards, so an analyst can still see that one host appears in
many lines. Each run uses a fresh random key, so pseudonyms cannot be linked across runs.

A private key printed over several lines is redacted line by line. The redactor remembers that a
key is open until its END line, or until a line that cannot belong to it, so one redactor has to
see a shard's lines in order, and ``shard_end`` keeps shards from splitting a key.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from aria.contracts.parsing import RedactionSummary

# (kind, pattern). Each match becomes [REDACTED], unless _KEEP says the match is not a secret.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----",
            re.DOTALL,
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{30,})\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("slack_webhook", re.compile(r"(?i)(?<=hooks\.slack\.com/services/)[A-Za-z0-9/_-]+")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![\w-])")),
    ("stripe_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}\b")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}(?![\w-])")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("basic_auth", re.compile(r"(?i)(?<=basic )\s*[A-Za-z0-9+/]{4,}={0,2}(?![\w+/=])")),
    ("url_credentials", re.compile(r"(?i)(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
)
# A name that holds a secret: one of these words, at the end of the name or before "_" or "-"
# (DB_PASSWORD, aws_secret_access_key, x-api-key, spring.datasource.password), or a SAS "sig".
# A word before "." names a namespace, as in a stack frame's AppWindowToken.destroySurfaces:374.
_SECRET_NAME = re.compile(
    r"(?i)(?:password|passwd|passphrase|pwd|secret|token|credentials?"
    r"|(?:api|access|account|private|encryption|signing|master|client)[_-]?key)(?:$|[_-])|^sig$"
)
# A whole name (possessive, so each name is tried once and the scan stays linear) and the "=" or
# ":" after it, quoted as in JSON (also escaped, as in a JSON log message), or a --flag.
_NAME_SEP = re.compile(r"(?<![\w.-])-*([A-Za-z_][\w.-]{0,127}+)(\\?[\"']?\s*[=:]\s*)")
_VALUE = re.compile(r"\\\"[^\"\\]*\\\"|\"[^\"]*\"|'[^']*'|[^\s,;]+")
_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
_KEY_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")
_KEY_LINE = re.compile(r"\s*[A-Za-z0-9+/]+={0,2}\s*")  # a whole line of a key's base64 body
_KEY_TAIL = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}\s*$")  # or one after a log line's prefix
_KEY_HEADER = re.compile(r"(?i)^\s*(?:proc-type|dek-info|version|comment|hash)\s*:")
# Card shapes only: one contiguous run, or 4-digit groups split by one space or dash, standing
# alone (not glued to letters, "_" or "-", as in HDFS's blk_5165786360127153975). Combined with an
# issuer prefix (3-6) and the Luhn check this avoids eating IDs, timestamps and counters in logs.
_CARD = re.compile(r"(?<![\w.:-])(?:\d{4}(?:[ -]\d{4}){2}[ -]\d{1,7}|\d{13,19})(?![\w.:-])")
# An address starts only where a run of address characters starts (the look-behind), so a long
# run of "a.a.a..." with no address in it costs one attempt, linear in its length, not one
# attempt per character (which made redaction quadratic). The local part has no length limit: a
# log can hold one longer than RFC 5321's 64 characters, and a missed address is a leak.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b"
)
_IPV4 = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
)
_IPV6 = re.compile(
    r"(?<![\w:])(?:"
    r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"  # the full form
    r"|(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?"  # or compressed: groups, "::", groups
    r"::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?"
    r")(?![\w:])"
)
_DIGIT_RUN = re.compile(r"\d{4}")  # every card shape contains four consecutive digits
# Literal parts at least one of which must appear (lowercased) for each secret pattern to match.
_TRIGGERS: dict[str, tuple[str, ...]] = {
    "private_key": ("private key-----",),
    "jwt": ("eyj",),
    "aws_access_key": ("akia", "asia"),
    "nvidia_key": ("nvapi-",),
    "openai_key": ("sk-",),
    "github_token": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"),
    "gitlab_token": ("glpat-",),
    "slack_token": ("xoxa-", "xoxb-", "xoxp-", "xoxr-", "xoxs-"),
    "slack_webhook": ("hooks.slack.com/services/",),
    "google_api_key": ("aiza",),
    "stripe_key": ("_live_", "_test_"),
    "sendgrid_key": ("sg.",),
    "bearer_token": ("bearer",),
    "basic_auth": ("basic ",),
    "url_credentials": ("://",),
}
_ASSIGNED_TRIGGERS = ("pass", "pwd", "secret", "key", "token", "credential", "sig")


def _basic_credentials(match: re.Match[str]) -> bool:
    """Whether a "Basic" token decodes to user:password (so "basic configuration" stays)."""
    try:
        decoded = base64.b64decode(match.group(0).strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    return ":" in decoded


# Kinds whose matches need a second look before they count as secrets.
_KEEP: dict[str, Callable[[re.Match[str]], bool]] = {
    "basic_auth": lambda match: not _basic_credentials(match),
}


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def new_salt() -> bytes:
    return secrets.token_bytes(16)


def is_secret_name(name: str) -> bool:
    """Whether a setting or label with this name holds a secret (``DB_PASSWORD``, ``api-key``)."""
    return _SECRET_NAME.search(name) is not None


def _key_open_after(line: str, is_open: bool) -> bool:
    """Whether a private key printed over several lines is still open after this line."""
    if "PRIVATE KEY" not in line:
        return is_open
    begins = [m.end() for m in _KEY_BEGIN.finditer(line)]
    ends = [m.end() for m in _KEY_END.finditer(line)]
    if not begins:
        return is_open and not ends
    return not ends or max(begins) > max(ends)


def shard_end(lines: Sequence[str], start: int, end: int) -> int:
    """Move a shard's end past a private key printed across it, so no shard starts inside one.

    Only a redactor that saw a key's BEGIN line knows to redact the lines after it.
    """
    is_open = False
    for line in lines[start:end]:
        is_open = _key_open_after(line, is_open)
    while is_open and end < len(lines):
        is_open = _key_open_after(lines[end], is_open)
        end += 1
    return end


@dataclass
class Redactor:
    pseudonymize_ips: bool = True
    salt: bytes = field(default_factory=new_salt, repr=False)
    counts: dict[str, int] = field(default_factory=dict)
    pseudonyms: set[str] = field(default_factory=set)
    _in_key: bool = field(default=False, init=False, repr=False)  # inside a multi-line key

    def _count(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n

    def _pseudonym(self, kind: str, value: str) -> str:
        digest = hmac.new(self.salt, f"{kind}:{value}".encode(), "sha256").hexdigest()[:8]
        pseudonym = f"{kind}-{digest}"
        self.pseudonyms.add(pseudonym)
        return pseudonym

    def _hide(self, kind: str, pattern: re.Pattern[str], text: str) -> str:
        keep = _KEEP.get(kind)
        if keep is None:
            text, found = pattern.subn("[REDACTED]", text)
        else:
            found = 0

            def hide(match: re.Match[str]) -> str:
                nonlocal found
                if keep(match):
                    return match.group(0)
                found += 1
                return "[REDACTED]"

            text = pattern.sub(hide, text)
        if found:
            self._count(kind, found)
        return text

    def _key_lines(self, text: str) -> str:
        """Redact a private key printed over several lines, one line at a time."""
        if not self._in_key:
            begin = _KEY_BEGIN.search(text)
            if begin is None or _KEY_END.search(text, begin.end()):
                return text  # no key, or a whole key in this text (the private_key pattern's)
            self._in_key = True
            self._count("private_key")
            return text[: begin.start()] + "[REDACTED]"
        end = _KEY_END.search(text)
        head = text if end is None else text[: end.start()]
        hidden = head
        if head.strip():
            tail = _KEY_TAIL.search(head)
            if _KEY_LINE.fullmatch(head):
                hidden = "[REDACTED]"
            elif tail is not None:
                hidden = head[: tail.start()] + "[REDACTED]"
            elif end is None and not _KEY_HEADER.match(head):
                self._in_key = False  # the key ended without its END line: an ordinary line
                return text
        if end is not None:
            self._in_key = False
            return hidden + "[REDACTED]" + text[end.end() :]
        return hidden

    def _assigned_secrets(self, text: str) -> str:
        """Redact the value of every secret-named setting (password=…, "api_key": "…")."""
        parts: list[str] = []
        done = 0
        for match in _NAME_SEP.finditer(text):
            if match.start() < done or not _SECRET_NAME.search(match.group(1)):
                continue
            value = _VALUE.match(text, match.end())
            if value is None or value.group(0) == "[REDACTED]":
                continue
            parts += [text[done : match.end()], "[REDACTED]"]
            done = value.end()
            self._count("assigned_secret")
        return "".join(parts) + text[done:] if parts else text

    def redact(self, text: str) -> str:
        if self._in_key or "PRIVATE KEY" in text:
            text = self._key_lines(text)
        lowered = text.lower()
        for kind, pattern in _SECRET_PATTERNS:
            if any(word in lowered for word in _TRIGGERS[kind]):
                text = self._hide(kind, pattern, text)  # (it cannot match without one of them)
        if any(word in lowered for word in _ASSIGNED_TRIGGERS):
            text = self._assigned_secrets(text)

        def card(match: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            if 13 <= len(digits) <= 19 and digits[0] in "3456" and _luhn_ok(digits):
                self._count("payment_card")
                return "[REDACTED]"
            return match.group(0)

        if _DIGIT_RUN.search(text):
            text = _CARD.sub(card, text)

        def email(match: re.Match[str]) -> str:
            self._count("email")
            return self._pseudonym("email", match.group(0).lower())

        if "@" in text:
            text = _EMAIL.sub(email, text)
        if self.pseudonymize_ips:

            def ip(match: re.Match[str]) -> str:
                self._count("ip")
                return self._pseudonym("ip", match.group(0))

            def ip6(match: re.Match[str]) -> str:
                value = match.group(0)
                if value == "::":  # a separator, not the unspecified address
                    return value
                try:
                    ipaddress.IPv6Address(value)
                except ValueError:
                    return value
                return ip(match)

            if text.count(".") >= 3:
                text = _IPV4.sub(ip, text)
            if "::" in text or text.count(":") >= 7:
                text = _IPV6.sub(ip6, text)
        return text

    def summary(self) -> RedactionSummary:
        return RedactionSummary(counts=dict(self.counts), pseudonyms=len(self.pseudonyms))
