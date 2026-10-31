"""Write the logs the web console offers to try: in chat, and on "Your own logs".

    uv run python -I scripts/export_web_samples.py

Each sample is a semi-synthetic incident window composed from real Loghub sample lines (the same
scenario builder the evaluation uses), so runs started from one are labelled synthetic. Writes:

- web/src/data/samples.json, the list the console loads with the page: each sample's id, what it
  shows, the system that wrote it, and whether it is an incident or routine noise;
- web/src/data/samples/<id>.json, each sample's lines, which the console loads only when someone
  picks that sample;
- web/src/data/sample-lines.ts, one dynamic import per sample, so each file is a chunk of its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals.run import FIXTURES_DIR

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "src" / "data"
INDEX = DATA / "samples.json"
LINES = DATA / "samples"
LOADERS = DATA / "sample-lines.ts"
MAX_LINES = 220

# One log for each scenario mode: the mode, the seed of its window, and what it shows in a few
# plain words (one line on the console's narrowest card). The console names the system that wrote
# the log, so the words leave the system out.
SAMPLES = (
    # Security and sign-ins
    ("linux.auth_failures", 11, "Sign-ins keep failing"),
    ("openssh.bruteforce", 12, "Someone guesses passwords"),
    # Phones and computers
    ("mac.cocoa_scripting_noise", 14, "Harmless app errors"),
    ("android.permission_noise", 13, "Harmless permission warnings"),
    # Web and cloud
    ("apache.mod_jk_worker_error", 12, "Its app servers stop answering"),
    ("openstack.image_cache_missing", 14, "Disk images go missing"),
    ("proxifier.proxy_connectivity", 11, "Proxy connections fail"),
    # Big-data clusters
    ("hdfs.block_serve_exceptions", 11, "Servers stop sending data"),
    ("hadoop.resourcemanager_unreachable", 12, "Tasks can’t reach the scheduler"),
    ("hadoop.hdfs_lease_renewal", 13, "Tasks lose their hold on files"),
    ("zookeeper.quorum_connection_loss", 13, "Servers lose touch"),
    ("zookeeper.old_client_noise", 14, "Notices about old clients"),
    # Supercomputers
    ("bgl.kernel_panic", 11, "Compute nodes crash"),
    ("bgl.memory_interrupts", 12, "Memory faults stop jobs"),
    ("bgl.lustre_mount_failure", 13, "Shared storage won’t mount"),
    ("bgl.ciod_link_failure", 14, "Nodes lose their control link"),
    ("bgl.tree_network_errors", 11, "Its network drops packets"),
    ("hpc.interconnect_link_errors", 12, "Links between servers fail"),
    ("hpc.component_unavailable", 13, "Hardware drops out of service"),
    ("hpc.psu_failure", 14, "Power supplies fail"),
)


def main() -> None:
    full = ROOT / "data" / "raw" / "loghub-2k"
    builder = ScenarioBuilder(LinePools.from_loghub(full if full.is_dir() else ROOT / FIXTURES_DIR))
    modes = builder.pools.modes
    index: list[dict[str, Any]] = []
    LINES.mkdir(parents=True, exist_ok=True)
    for mode, seed, label in SAMPLES:
        scenario = builder.build(
            mode, seed=seed, nodes=5, duration_min=8, background_per_min=8, incident_per_min=9
        )
        entry = {
            "id": mode,
            "label": label,
            "system": scenario.system,
            # Noise that needs no action is routine; everything else is an incident.
            "kind": "routine" if modes[mode].benign else "incident",
        }
        index.append(entry)
        lines = scenario.lines[:MAX_LINES]
        _write(LINES / f"{mode}.json", {**entry, "synthetic": True, "lines": lines})
        print(f"{mode}: {len(lines)} lines")
    # A sample no longer offered leaves no file behind for the console to bundle.
    offered = {mode for mode, _, _ in SAMPLES}
    for stale in LINES.glob("*.json"):
        if stale.stem not in offered:
            stale.unlink()
    _write(INDEX, index)
    LOADERS.write_text(_loaders([entry["id"] for entry in index]), encoding="utf-8")
    print(f"wrote {INDEX}, {LOADERS.name} and {len(index)} samples in {LINES}")
    if missing := [mode for mode in modes if mode not in offered]:
        print("scenario modes with no sample: " + ", ".join(missing))


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _loaders(ids: list[str]) -> str:
    """A literal import() per sample: a bundler splits each into a chunk the page fetches only
    when it runs (a glob of the folder was bundled whole into the page)."""
    entries = "".join(
        f"  [{json.dumps(mode)}, () => import({json.dumps(f'./samples/{mode}.json')})],\n"
        for mode in ids
    )
    return (
        "// Written by scripts/export_web_samples.py; do not edit. Each sample's lines are a chunk\n"
        "// of their own, which the console fetches only when someone picks that sample.\n"
        "const sampleLines = new Map<string, () => Promise<{ default: { lines: string[] } }>>([\n"
        f"{entries}"
        "]);\n\n"
        "export default sampleLines;\n"
    )


if __name__ == "__main__":
    main()
