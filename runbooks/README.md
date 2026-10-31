# Runbooks

Example runbooks that ARIA retrieves and cites when it recommends actions. They are written for
the systems in the public Loghub datasets (BlueGene/L, HDFS, Hadoop, ZooKeeper, OpenSSH, HPC,
OpenStack, Apache, Proxifier) and are **examples to adapt**, not procedures validated in your
environment.

Format: YAML front matter (`slug`, `title`, `systems`, `failure_modes`, `risk`), then the
sections `When to use`, `Diagnose`, `Mitigate`, `Verify` and `Escalate`. Numbered items under
`Diagnose` and `Mitigate` become steps ARIA can quote. A step ending in `[risk: medium]` or
`[risk: high]` is flagged in reports and needs human approval before anyone acts on it.
