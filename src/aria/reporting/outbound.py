"""What an outbound draft may carry: links to allowed hosts and configured recipients only.

A message draft quotes the report, which quotes logs, alert labels and whatever a model wrote.
Before a reviewer sees a draft, every link whose host is not on the allow-list and every
mention or address that is not a configured recipient is taken out of it, and each removal is
listed for the reviewer as "removed from the draft". Nothing is kept silently.

* **Links**: a URL (``https://...``, ``www....``), a bare domain such as ``status-help.com``,
  a Markdown link, and any ``javascript:``, ``data:`` or ``mailto:`` target. Chat tools turn a
  bare domain into a link, so it counts as one. A link may point only to ARIA's own console and
  API (where reports and runbooks live) or to a host in ``comms.link_hosts``; a subdomain counts
  as its host.
* **Recipients**: ``@handles`` (``@channel`` and ``@here`` included), ``#channels``, e-mail
  addresses, and Slack's and Teams' mention markup. Only those in ``comms.recipients`` stay.

The reviewer's list names a removed link by its host and a removed address as written, both
with their dots bracketed (``evil[.]example``), so the list itself never becomes a link.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from aria.config import CommsConfig, Settings

LINK_REMOVED = "[link removed]"
RECIPIENT_REMOVED = "[recipient removed]"

# Top-level domains chat tools link without a scheme: the common generic ones, and those most
# used for throwaway or look-alike sites. A file name such as "hdfs.py" is left alone.
_TLDS = (
    "com|net|org|io|co|dev|app|info|biz|me|ly|example|ai|xyz|site|online|top|link|click|cloud|"
    "tech|store|shop|live|page|zip|mov|ru|cn|tk|us|uk|de|eu|in|gg|tv|cc|ws|to|su"
)
_STOP = "\\s<>\"'`|"  # characters that end a URL in running text
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{0,300})\]\(\s*((?:[^()\s]|\([^()\s]*\))+)[^)\n]*\)")
_SCHEME_URL = re.compile(rf"(?i)\b(?:https?|ftps?|wss?)://[^{_STOP}]+")
_UNSAFE_TARGET = re.compile(rf"(?i)\b(?:javascript|vbscript|data|file):[^{_STOP}]+")
_MAILTO = re.compile(rf"(?i)\bmailto:[^{_STOP}]+")
_WWW = re.compile(rf"(?i)\bwww\.[^{_STOP}]+")
# A host ends where a dotted name ends: "java.io.IOException" is a class, not the host java.io.
_BARE_DOMAIN = re.compile(
    rf"(?i)(?<![\w@./:-])(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_TLDS})(?![\w-]|\.\w)"
    rf"(?::\d{{1,5}})?(?:/[^{_STOP}]*)?"
)
_EMAIL = re.compile(r"(?<![\w.+%-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_SLACK_MENTION = re.compile(
    r"<(?:!(?:channel|here|everyone)|![a-z]+\^[^>]{1,40}|[@#][A-Z0-9]{2,20})(?:\|[^>]*)?>"
)
_TEAMS_MENTION = re.compile(r"(?i)<at>[^<]{0,100}</at>")
_HANDLE = re.compile(r"(?<![\w@.+%/-])@[A-Za-z0-9][\w.-]{0,79}")
_CHANNEL = re.compile(r"(?<![\w&#/])#(?=[\w-]*[A-Za-z])[A-Za-z0-9][\w-]{1,79}")
_TRAILING = ".,;:!?)]}'\""


def host_of(url: str | None) -> str:
    """The lower-cased host of ``url`` (with or without a scheme), or "" when it has none."""
    if not url:
        return ""
    target = url if "://" in url else f"http://{url}"
    try:
        return (urlsplit(target).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def defang(text: str) -> str:
    """``text`` with its dots bracketed, so no renderer turns it into a link."""
    return text.replace(".", "[.]")


@dataclass(frozen=True)
class DraftPolicy:
    """The hosts a draft may link to and the recipients it may address."""

    link_hosts: frozenset[str]
    recipients: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def for_settings(cls, settings: Settings, comms: CommsConfig) -> DraftPolicy:
        """ARIA's own console and API, plus the configured hosts and recipients."""
        own = {host_of(settings.console_url), host_of(settings.public_base_url)}
        return cls(
            link_hosts=frozenset(h for h in (*own, *comms.link_hosts) if h),
            recipients=frozenset(r.lower() for r in comms.recipients),
        )

    @classmethod
    def for_link(cls, url: str) -> DraftPolicy:
        """Only the host of ``url`` (the run's own link) and no recipients."""
        host = host_of(url)
        return cls(link_hosts=frozenset({host} if host else ()))

    def allows_host(self, host: str) -> bool:
        return bool(host) and any(host == h or host.endswith(f".{h}") for h in self.link_hosts)

    def allows_recipient(self, recipient: str) -> bool:
        return recipient.lower() in self.recipients


@dataclass
class Screened:
    text: str
    removed: list[str] = field(default_factory=list)


def _trim(match: str) -> tuple[str, str]:
    """A URL found in running text, without the punctuation that ends its sentence."""
    stripped = match.rstrip(_TRAILING)
    return stripped, match[len(stripped) :]


class _Screen:
    def __init__(self, policy: DraftPolicy) -> None:
        self.policy = policy
        self.removed: list[str] = []

    def _note(self, what: str) -> None:
        if what not in self.removed:
            self.removed.append(what)

    def _link(self, url: str) -> str | None:
        """None when ``url`` may stay, else what the reviewer is told was removed."""
        if _UNSAFE_TARGET.match(url) or _MAILTO.match(url):
            return f"link to a {url.split(':', 1)[0].lower()}: target"
        host = host_of(url)
        if self.policy.allows_host(host):
            return None
        return f"link to {defang(host) if host else 'an unreadable address'}"

    def markdown(self, match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        removed = self._link(target)
        if removed is None:
            return match.group(0)
        self._note(removed)
        return f"{label} {LINK_REMOVED}".strip()

    def url(self, match: re.Match[str]) -> str:
        url, tail = _trim(match.group(0))
        removed = self._link(url)
        if removed is None:
            return match.group(0)
        self._note(removed)
        return LINK_REMOVED + tail

    def recipient(self, match: re.Match[str]) -> str:
        found, tail = _trim(match.group(0))
        if self.policy.allows_recipient(found):
            return match.group(0)
        self._note(f"recipient {defang(found)}")
        return RECIPIENT_REMOVED + tail


def screen(text: str, policy: DraftPolicy) -> Screened:
    """``text`` with every link to a host off the allow-list and every recipient that is not
    configured taken out, and a description of each removal for the reviewer."""
    check = _Screen(policy)
    # Markdown first (its label stays, its target goes), then explicit targets, then addresses
    # (before a bare domain could match an address's domain), then bare hosts and mentions.
    text = _MARKDOWN_LINK.sub(check.markdown, text)
    for pattern in (_UNSAFE_TARGET, _MAILTO, _SCHEME_URL, _WWW):
        text = pattern.sub(check.url, text)
    for pattern in (_SLACK_MENTION, _TEAMS_MENTION, _EMAIL):
        text = pattern.sub(check.recipient, text)
    text = _BARE_DOMAIN.sub(check.url, text)
    for pattern in (_HANDLE, _CHANNEL):
        text = pattern.sub(check.recipient, text)
    return Screened(text, check.removed)


def screen_all(parts: Iterable[str], policy: DraftPolicy) -> tuple[list[str], list[str]]:
    """Several fields of one draft screened together: their cleaned text, and every removal
    once."""
    cleaned: list[str] = []
    removed: list[str] = []
    for part in parts:
        result = screen(part, policy)
        cleaned.append(result.text)
        removed.extend(r for r in result.removed if r not in removed)
    return cleaned, removed
