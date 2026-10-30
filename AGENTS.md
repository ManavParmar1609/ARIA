# AGENTS.md

Instructions for coding agents working on this repository. People should start with the
[README](README.md).

ARIA is an incident-triage service. Its parts:

- a LangGraph workflow in `src/aria/graph/`;
- a FastAPI service in `src/aria/api/`;
- a read-only MCP server in `src/aria/mcp/`;
- a Next.js console in `web/`;
- an evaluation harness in `src/aria/evals/` that produces every published number.

The specification and its acceptance checks are in [docs/build-brief.md](docs/build-brief.md).

## Set up

```bash
uv sync --all-groups --all-extras
```

```bash
pnpm --dir web install --frozen-lockfile
```

`make eval-smoke` needs the Loghub samples (a few MB, unlike `make data`'s full download):

```bash
uv run aria data download --source loghub-2k
```

Python 3.12+ with uv, Node 22.13+ with pnpm. In Claude Code cloud sessions,
`.claude/hooks/session-start.sh` does this for you.

## Check your work

Run what covers the files you changed before you commit:

| You changed | Run |
|---|---|
| Python | `make lint` (ruff format check, ruff, mypy `--strict`) and `make test` (80% coverage gate) |
| A quick Python loop | `make test-fast`, or `uv run pytest tests/unit/test_<area>.py -q` |
| API routes or schemas | `make openapi`, then commit `docs/openapi.json` and `web/src/lib/api/schema.ts` |
| `web/` | `make web-check`; for pages and flows, `make web-e2e` too |
| `video/` | `pnpm --dir video format:check`, `pnpm --dir video typecheck`, then `make video` |
| Severity, parsing, retrieval or reporting | `make eval-smoke` (the CI gate in `config/eval_thresholds.yaml`) |
| Anything a published number depends on | `make eval`, then commit what it rewrote |
| Workflows | `make audit` (actionlint, zizmor, pip-audit) |

Tests run offline: `tests/conftest.py` removes provider keys, so every LLM step uses the
deterministic fake provider and every test gets a fresh SQLite database. Keep it that way. A test
must never need a network call or a real key. Contract tests mock HTTP.

## Generated files: never edit by hand

| File | Comes from |
|---|---|
| `docs/evaluation.md`, `docs/eval-results.json` | `make eval` |
| Blocks between `<!-- generated:NAME -->` and `<!-- /generated:NAME -->` in `README.md` and `docs/model-card.md` | `make eval` |
| `docs/eval-live.json` | `uv run aria eval run --suite pipeline --llm` (makes paid or rate-limited provider calls; ask first) |
| `web/src/data/eval-results.json`, `web/src/data/eval-live.json`, `web/src/data/llms.json` | `pnpm --dir web sync:data` |
| `web/src/data/samples.json` | `uv run python -I scripts/export_web_samples.py` |
| `web/src/data/demo-run.json` | `uv run python -I scripts/record_demo_run.py` (the landing page and `video/` both read it) |
| `docs/openapi.json`, `web/src/lib/api/schema.ts` | `make openapi` |
| `models/*.json`, `models/*.npz` | `make train` and `aria seed` |
| `uv.lock`, `web/pnpm-lock.yaml` | `uv add` / `uv lock`, `pnpm add` |

Never type a measured number into a doc, a page or a commit message. Quote it from a generated
block, or link to `docs/evaluation.md`. `tests/unit/test_docs.py` fails when a generated block
falls out of date.

## Rules

- **Secrets.** Never put secrets in code, logs, fixtures or git. Config comes from environment
  variables (see `.env.example`) and Key Vault. `.env` is git-ignored. Don't print its values.
  A visitor's own model key (`X-Model-Key`) lives in memory for the work it came with: never
  store, log or echo it.
- **Raw data.** Keep raw datasets out of git. Add a source to `data/manifest.yaml` with a pinned
  commit or checksum, and commit only small fixtures under `tests/fixtures/`.
- **Untrusted log text.** Log lines, alert labels and annotations are untrusted input. They reach
  a model only through the fenced evidence blocks in `src/aria/llm/prompts.py`, after redaction
  and the injection guard in `src/aria/security/`. Never interpolate them into instructions.
- **MCP tools.** Keep MCP tools read-only, annotated and argument-bounded. A tool that writes,
  sends or deletes does not belong in `src/aria/mcp/server.py`.
- **Outbound actions.** Every outbound post or ticket draft goes through the review interrupt.
  Don't add a path that sends before approval.
- **Severity.** An LLM may only choose inside the conformal prediction set. Keep the rule floors
  and the conservative policy in `src/aria/severity/` intact.
- **Model IDs.** These change fast. Put them in `config/aria.yaml` with `verified: true` only
  after a live call, and record the date in `notes`.
- **Stop and ask before** pushing to a branch other than the one you were given, creating cloud
  resources, spending provider credits, deleting user files, or adding a paid service.

## Code conventions

- **Python.**
  - Typed and `mypy --strict` clean, ruff with line length 100.
  - Pydantic v2 contracts live in `src/aria/contracts/` and check every handoff between nodes.
  - Async handlers must not block: wrap database and CPU work in `asyncio.to_thread`.
- **Tests.**
  - pytest with `asyncio_mode = "auto"` and Hypothesis for properties.
  - Mark long tests `@pytest.mark.slow`.
  - Name a test for the behaviour it checks.
- **Web.**
  - Next.js App Router, strict TypeScript, Tailwind v4.
  - The browser calls only the app's own `/api/*` routes, which forward to the ARIA API with the
    signed-in key (`web/src/lib/server/upstream.ts`).
  - Every view needs loading, empty and error states. Respect `prefers-reduced-motion` and WCAG
    2.2 AA.
  - Read [web/DESIGN.md](web/DESIGN.md) before changing the look.
- **Writing.**
  - Docs, UI copy and commit messages are plain English, in sentence case and the active voice.
  - Name things by what users see, not how they are built.
  - Commit subjects are imperative ("Add the log scan trigger").

## Where things are

| Path | Contents |
|---|---|
| `src/aria/graph/workflow.py` | Graph nodes, routing, review interrupt, publish and learn |
| `src/aria/graph/runner.py` | Starting, resuming and forking runs |
| `src/aria/severity/` | Rules, features, model, conformal sets, recalibration |
| `src/aria/reporting/` | Report writer, critic, validator, comms drafts |
| `src/aria/llm/` | Providers, router, budgets, prompts |
| `src/aria/api/` | App, routers, webhooks, log scan, A2A, AG-UI, worker |
| `src/aria/evals/` | Suites, metrics and the report generator. Real data: `real.py` (HDFS, expert labels), `bgl.py` (BGL alert tags), `hadoop.py` (failed jobs), `openstack.py` (injected bugs), `tickets.py` (ServiceNow tickets), `gitlab.py` (GitLab.com incidents), `postmortems.py` (cloud post-mortems), `injection.py` (public injection benchmarks) |
| `src/aria/parsing/flows.py` | Units of work that stop partway, learned per window (`config/flows.yaml`) |
| `src/aria/data/real.py` | Real, labelled logs and the real incidents the console replays |
| `src/aria/data/download.py` | Fetching and verifying manifest sources, with checksum-pinned mirrors for blocked hosts |
| `src/aria/cli.py` | The `aria` command |
| `tests/unit/` | One file per area, for example `test_severity.py` |
| `web/src/app/` | Landing page (`page.tsx`) and console (`console/`) |
| `web/e2e/` | Playwright and axe tests |
| `video/src/` | The Remotion explainer: one scene per pipeline step, data from `web/src/data/demo-run.json` and `docs/eval-results.json` |
| `docs/adr/` | Why the architecture is the way it is |
| `deploy/demo/Dockerfile`, `render.yaml` | The free public demo: open, offline and seeded at build time ([docs/deploy-free.md](docs/deploy-free.md)) |
