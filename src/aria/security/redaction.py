"""Remove secrets and personal data from log text before it is stored or shown to an LLM.

Secrets are replaced outright. Identifiers that matter for triage (IP addresses, e-mail addresses)
are pseudonymised with a keyed hash: within one run ``10.0.0.7`` always becomes the same
``ip-3fa2c1d0``, even across parallel shards, so an analyst can still see that one host appears in
many lines. Each run uses a fresh random key, so pseudonyms cannot be linked across runs.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field

from aria.contracts.parsing import RedactionSummary

# (kind, pattern, replacement). Replacement None means pseudonymise.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("url_credentials", re.compile(r"(?i)(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token|client[_-]?secret)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
        ),
    ),
)
# Card shapes only: one contiguous run, or 4-digit groups split by one space or dash, standing
# alone (not glued to letters, "_" or "-", as in HDFS's blk_5165786360127153975). Combined with an
# issuer prefix (3-6) and the Luhn check this avoids eating IDs, timestamps and counters in logs.
_CARD = re.compile(r"(?<![\w.:-])(?:\d{4}(?:[ -]\d{4}){2}[ -]\d{1,7}|\d{13,19})(?![\w.:-])")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
)
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![\w:])")
_DIGIT_RUN = re.compile(r"\d{4}")  # every card shape contains four consecutive digits
# Literal parts at least one of which must appear (lowercased) for each secret pattern to match.
_TRIGGERS: dict[str, tuple[str, ...]] = {
    "private_key": ("private key-----",),
    "jwt": ("eyj",),
    "aws_access_key": ("akia", "asia"),
    "nvidia_key": ("nvapi-",),
    "openai_key": ("sk-",),
    "github_token": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"),
    "slack_token": ("xoxa-", "xoxb-", "xoxp-", "xoxr-", "xoxs-"),
    "bearer_token": ("bearer",),
    "url_credentials": ("://",),
    "assigned_secret": ("pass", "pwd", "secret", "key", "token"),
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


@dataclass
class Redactor:
    pseudonymize_ips: bool = True
    salt: bytes = field(default_factory=new_salt, repr=False)
    counts: dict[str, int] = field(default_factory=dict)
    pseudonyms: set[str] = field(default_factory=set)

    def _count(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n

    def _pseudonym(self, kind: str, value: str) -> str:
        digest = hmac.new(self.salt, f"{kind}:{value}".encode(), "sha256").hexdigest()[:8]
        pseudonym = f"{kind}-{digest}"
        self.pseudonyms.add(pseudonym)
        return pseudonym

    def redact(self, text: str) -> str:
        lowered = text.lower()
        for kind, pattern in _SECRET_PATTERNS:
            if not any(word in lowered for word in _TRIGGERS[kind]):
                continue  # the pattern cannot match without one of its literal parts
            if kind == "assigned_secret":
                text, n = pattern.subn(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
            else:
                text, n = pattern.subn("[REDACTED]", text)
            if n:
                self._count(kind, n)

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

            if text.count(".") >= 3:
                text = _IPV4.sub(ip, text)
            if text.count(":") >= 7:
                text = _IPV6.sub(ip, text)
        return text

    def summary(self) -> RedactionSummary:
        return RedactionSummary(counts=dict(self.counts), pseudonyms=len(self.pseudonyms))
