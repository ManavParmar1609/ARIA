"""Write the sample log windows the web console offers: in chat, and on "Your own logs".

    uv run python -I scripts/export_web_samples.py

Each sample is a semi-synthetic incident window composed from real Loghub sample lines (the same
scenario builder the evaluation uses), so runs started from one are labelled synthetic.
Writes web/src/data/samples.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals.run import FIXTURES_DIR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "data" / "samples.json"
SAMPLES = (
    ("hdfs.block_serve_exceptions", 11, "DataNodes failing to serve blocks"),
    ("openssh.bruteforce", 12, "SSH brute-force attempts"),
    ("zookeeper.quorum_connection_loss", 13, "ZooKeeper quorum connection loss"),
    ("mac.cocoa_scripting_noise", 14, "Benign Cocoa scripting noise"),
    # Logs most people recognise, offered on "Your own logs" to fill the box in one click.
    ("linux.auth_failures", 11, "Repeated sign-in failures on Linux servers"),
    ("apache.mod_jk_worker_error", 12, "An Apache web server losing its backends"),
    ("android.permission_noise", 13, "Harmless permission warnings on an Android phone"),
    ("openstack.image_cache_missing", 14, "OpenStack servers missing their disk images"),
)


def main() -> None:
    full = ROOT / "data" / "raw" / "loghub-2k"
    builder = ScenarioBuilder(LinePools.from_loghub(full if full.is_dir() else ROOT / FIXTURES_DIR))
    samples = []
    for mode, seed, label in SAMPLES:
        scenario = builder.build(
            mode, seed=seed, nodes=5, duration_min=8, background_per_min=8, incident_per_min=9
        )
        samples.append(
            {
                "id": mode,
                "label": label,
                "system": scenario.system,
                "lines": scenario.lines[:220],
                "synthetic": True,
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(samples, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: " + ", ".join(f"{s['id']} ({len(s['lines'])} lines)" for s in samples))


if __name__ == "__main__":
    main()
