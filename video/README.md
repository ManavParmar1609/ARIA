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

The look follows [web/DESIGN.md](../web/DESIGN.md), the cream-paper style reference: cream
paper, white cards, ink text, Inter, and grass green for panels and highlights. The film opens on
the landing page's green hero, with its illustrated crew riding in, and closes on the approval
scene, where the message flies only after the thumbs-up. Both illustrations are imported from
`web/src/components/illustrations`, so the site and the film never drift apart. Each scene has
one moving thing.
