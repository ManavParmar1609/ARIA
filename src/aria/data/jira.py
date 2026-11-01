"""The Public Jira Dataset (Montgomery, Lüders and Maalej, MSR 2022): issues and the priority
people gave them, from public Jira instances.

The dataset is one 5.8 GB zip on Zenodo, holding a gzipped ``mongodump`` archive with one
collection per Jira instance. ARIA never downloads it whole: it finds the archive inside the zip
with range requests, reads it as it streams in, keeps the first ``limit`` issues of each instance
the manifest names (in the archive's own order) and stops once it has them. Each kept issue is
cut down to the fields a ticket has when it is opened, plus its final priority and the priority
it opened with (from its change history), and written to ``<instance>.jsonl``.

Priority names differ per instance, so each instance's scale is mapped onto ARIA's four ticket
levels (1 most urgent) by its own written order. Issues whose priority is unset, or a name the
mapping does not know, carry no level and are left out of scoring.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from aria.data import mongodump, remote_zip
from aria.data.manifest import DataSource

JIRA_DIR = Path("data/raw/jira-public")
JIRA_CITATION = (
    "L. Montgomery, C. Lüders, W. Maalej. An Alternative Issue Tracking Dataset of Public Jira "
    "Repositories. MSR 2022. Zenodo, DOI 10.5281/zenodo.15719919."
)
# Each instance's priorities, most urgent first, on ARIA's four ticket levels.
PRIORITY_LEVELS: dict[str, dict[str, str]] = {
    "Apache": {"Blocker": "1", "Critical": "2", "Major": "3", "Minor": "4", "Trivial": "4"},
    "Jira": {"Highest": "1", "High": "2", "Medium": "3", "Low": "4", "Lowest": "4"},
}
MAX_TEXT = 2_000  # characters of a description kept: enough to read what the issue is about


@dataclass(frozen=True)
class Issue:
    instance: str
    key: str
    project: str
    issue_type: str
    priority: str  # the final priority's name; "" when unset
    priority_at_open: str  # the name it opened with, from the change history
    created: datetime | None
    summary: str
    description: str
    components: tuple[str, ...]

    @property
    def level(self) -> str | None:
        return PRIORITY_LEVELS.get(self.instance, {}).get(self.priority)

    @property
    def level_at_open(self) -> str | None:
        return PRIORITY_LEVELS.get(self.instance, {}).get(self.priority_at_open)


def _name(value: Any) -> str:
    return str(value.get("name") or "") if isinstance(value, Mapping) else ""


def _opened_with(doc: Mapping[str, Any], final: str) -> str:
    """The priority the issue was created with: the 'from' of its first priority change, or the
    final priority when it never changed."""
    histories = (doc.get("changelog") or {}).get("histories") or []
    changes = sorted(
        (str(h.get("created") or ""), str(item.get("fromString") or ""))
        for h in histories
        if isinstance(h, Mapping)
        for item in h.get("items") or []
        if isinstance(item, Mapping) and item.get("field") == "priority"
    )
    return changes[0][1] if changes else final


def issue_record(instance: str, doc: Mapping[str, Any]) -> dict[str, Any]:
    """The kept fields of one issue document, as stored in the subset."""
    fields = doc.get("fields") or {}
    final = _name(fields.get("priority"))
    project = fields.get("project")
    return {
        "instance": instance,
        "key": str(doc.get("key") or ""),
        "project": str(project.get("key") or "") if isinstance(project, Mapping) else "",
        "issue_type": _name(fields.get("issuetype")),
        "priority": final,
        "priority_at_open": _opened_with(doc, final),
        "created": str(fields.get("created") or ""),
        "summary": str(fields.get("summary") or ""),
        "description": str(fields.get("description") or "")[:MAX_TEXT],
        "components": [_name(c) for c in fields.get("components") or [] if _name(c)],
    }


def select(
    documents: Iterable[tuple[str, bytes]], keep: list[str], limit: int
) -> dict[str, list[dict[str, Any]]]:
    """The first ``limit`` issues of each kept instance, in archive order; reading stops once
    every kept instance has its share."""
    kept: dict[str, list[dict[str, Any]]] = {name: [] for name in keep}
    for collection, raw in documents:
        bucket = kept.get(collection)
        if bucket is None or len(bucket) >= limit:
            continue
        doc, _ = mongodump.decode(raw)
        bucket.append(issue_record(collection, doc))
        if all(len(b) >= limit for b in kept.values()):
            break
    return kept


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Rows as JSON lines with sorted keys, byte for byte the same on every run and machine.
    Plain text, not gzipped, so the manifest's pin does not depend on a zlib build."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with partial.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    partial.replace(path)


def write_subset(
    source: DataSource, dest: Path, client: httpx.Client, url: str | None
) -> list[Path]:
    """Stream reader for ``aria data download``: write ``<instance>.jsonl`` per kept one."""
    from aria.data.download import DownloadError, throttle_for  # noqa: PLC0415 - import cycle

    stream = source.stream
    if stream is None or not url or not stream.member or not stream.keep or not stream.limit:
        msg = f"{source.name}: the Jira reader needs a URL, member, keep and limit"
        raise DownloadError(msg)
    targets = [dest / f"{name.lower()}.jsonl" for name in stream.keep]
    if all(path.exists() for path in targets):
        return targets  # the download checks them against their pins
    throttle = throttle_for(url)
    before = throttle.wait if throttle is not None else None
    member = remote_zip.locate(client, url, stream.member, before=before)
    chunks = remote_zip.stream(client, url, member, before=before)
    try:
        kept = select(mongodump.documents(chunks), stream.keep, stream.limit)
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()  # stops the download once the subset is complete
    for name, path in zip(stream.keep, targets, strict=True):
        write_jsonl(path, kept[name])
    return targets


def _when(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return None


def read_issues(root: Path = JIRA_DIR) -> list[Issue]:
    """Every kept issue from every ``*.jsonl`` in ``root``, in file order."""
    issues: list[Issue] = []
    for path in sorted(root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                issues.append(
                    Issue(
                        instance=str(row.get("instance") or ""),
                        key=str(row.get("key") or ""),
                        project=str(row.get("project") or ""),
                        issue_type=str(row.get("issue_type") or ""),
                        priority=str(row.get("priority") or ""),
                        priority_at_open=str(row.get("priority_at_open") or ""),
                        created=_when(str(row.get("created") or "")),
                        summary=str(row.get("summary") or ""),
                        description=str(row.get("description") or ""),
                        components=tuple(str(c) for c in row.get("components") or []),
                    )
                )
    return issues
