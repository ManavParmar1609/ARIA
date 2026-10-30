"""The docs stay true: quoted results match `make eval`, links resolve, agent files match the code."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from aria.data.loghub import SYSTEMS
from aria.evals import report
from aria.mcp.server import PROMPT_NAMES, TOOL_NAMES

ROOT = Path(__file__).resolve().parents[2]
DOCS = sorted(
    [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *(ROOT / "docs").rglob("*.md"),
        *(ROOT / "skills").rglob("*.md"),
        *(ROOT / "runbooks").glob("*.md"),
    ]
)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
REPO_RAW = "https://raw.githubusercontent.com/ManavParmar1609/ARIA/main/"
SKILL = ROOT / "skills" / "aria-triage" / "SKILL.md"


def _committed_results() -> tuple[dict[str, object], dict[str, object]]:
    results = json.loads((ROOT / "docs" / "eval-results.json").read_text(encoding="utf-8"))
    live = json.loads((ROOT / "docs" / "eval-live.json").read_text(encoding="utf-8"))
    return results, live


@pytest.mark.parametrize("doc", report.QUOTING_DOCS, ids=str)
def test_quoted_results_are_the_ones_make_eval_writes(doc: Path) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "<!-- generated:" in text, f"{doc} quotes no generated results"
    expected = report.fill(text, report.blocks(*_committed_results()))
    assert text == expected, f"{doc} is out of date: run `make eval`"


def test_generated_blocks_are_rewritten_in_place() -> None:
    text = "intro\n<!-- generated:results -->\nold\n<!-- /generated:results -->\noutro\n"
    assert report.fill(text, {"results": "new\n"}) == (
        "intro\n<!-- generated:results -->\nnew\n<!-- /generated:results -->\noutro\n"
    )
    with pytest.raises(ValueError, match="no content"):
        report.fill(text, {})
    results, live = _committed_results()
    summary = report.blocks(results, live)["results"]
    assert "semi-synthetic" in summary
    assert "docs/evaluation.md" in summary


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    broken = []
    for target in LINK.findall(doc.read_text(encoding="utf-8")):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path = (doc.parent / target.split("#", 1)[0]).resolve()
        if not path.exists():
            broken.append(target)
    assert not broken, f"broken links in {doc.relative_to(ROOT)}: {broken}"


def test_llms_txt_points_at_files_in_this_repo_and_the_site_serves_it() -> None:
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# ARIA\n\n> ")
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    assert links
    for url in links:
        assert url.startswith(REPO_RAW), url
        assert (ROOT / url.removeprefix(REPO_RAW)).is_file(), url
    served = json.loads((ROOT / "web" / "src" / "data" / "llms.json").read_text(encoding="utf-8"))
    assert served["text"] == text, "run `pnpm --dir web sync:data`"


def test_the_agent_skill_is_valid_and_matches_the_code() -> None:
    text = SKILL.read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    assert meta["name"] == SKILL.parent.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
    assert len(meta["name"]) <= 64
    assert 0 < len(meta["description"]) <= 1024
    assert body.strip().startswith("# ")

    tools = re.search(r"Tools: (.+?)\.\s", body, re.DOTALL)
    assert tools is not None
    assert re.findall(r"`([a-z_]+)`", tools.group(1)) == list(TOOL_NAMES)
    prompts = re.search(r"Prompts:(.+?)Resources:", body, re.DOTALL)
    assert prompts is not None
    assert re.findall(r"`([a-z_]+)`", prompts.group(1)) == list(PROMPT_NAMES)
    systems = re.search(r"`system` is the log format\. One of: (.+?)\.\n", body, re.DOTALL)
    assert systems is not None
    assert sorted(re.findall(r"`([a-z]+)`", systems.group(1))) == sorted(SYSTEMS)
