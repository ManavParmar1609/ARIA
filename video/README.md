# ARIA explainer video

An 84-second explainer built with [Remotion](https://www.remotion.dev) from real output only.

- **The run** is `web/src/data/demo-run.json`: one ARIA run recorded by
  `scripts/record_demo_run.py`, on a semi-synthetic HDFS incident with one planted
  prompt-injection line.
- **The numbers** come from `docs/eval-results.json`, which `make eval` writes.

Nothing on screen is typed in by hand: re-record the run or re-run the evaluation, then render
again.

```bash
pnpm install --frozen-lockfile
```

```bash
pnpm studio
```

```bash
pnpm render
```

`pnpm studio` opens a live preview. `pnpm render` writes `out/aria-demo.mp4`, and `make video`
does the same from the repo root. CI renders it on every push and uploads it as the `aria-demo`
artifact.

Remotion downloads its own headless Chrome. On a machine where it cannot, set
`REMOTION_BROWSER_EXECUTABLE` to a local Chrome Headless Shell. `node scripts/stills.mjs` renders
one still per scene into `out/stills/`, which makes layout review quick.

The scenes follow the pipeline in order:

1. intake, with the planted line quarantined;
2. parsing into templates;
3. severity: rules, model, prediction set;
4. investigation and similar incidents;
5. the cited report;
6. human review;
7. the measured results, with their caveat.

The look follows [web/DESIGN.md](../web/DESIGN.md), "a greenhouse on cream paper": cream paper,
forest ink, keylime, mint, sage and slate panels with no shadows, headlines in Newsreader at weight
300, Inter for everything else and Geist Mono for log lines. The film opens on the landing page's
hero, the promise on sage beside three cards from the recorded run rising on slate, and closes on
the landing page's last panel, its loose lines running together into one. Each scene has one
moving thing.
