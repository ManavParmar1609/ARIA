# ARIA

[![CI](https://github.com/ManavParmar1609/ARIA/actions/workflows/ci.yml/badge.svg)](https://github.com/ManavParmar1609/ARIA/actions/workflows/ci.yml)

ARIA does the first pass of incident triage. It reads an alert or a burst of log lines and works
out what failed, how severe it is and which past incidents look the same. It then drafts an
incident report in which every claim cites the log lines behind it, and pauses for a person to
approve, edit or reject the report before anything is published or sent.

ARIA runs offline with no API keys. Set a Gemini key (free tier available) or an NVIDIA NIM key,
and the agents write with hosted models. Azure OpenAI and any OpenAI-compatible server work the
same way: switching is a config change.

![ARIA's home page: the headline "Turn a wall of logs into a report you can check." on a sage-green panel, and beside it, on a slate-blue panel, a report card from a recorded run: the level, a claim with its citation open on the log line it cites, and a note that it is waiting for a person to approve.](docs/images/hero.webp)

> [!IMPORTANT]
> Several results use **real data with the labels its owners gave it**: a Hadoop cluster's log (the
> experts' label for every storage block), the whole BlueGene/L log (its administrators' alert
> tags), Hadoop jobs with injected failures, OpenStack runs with an injected bug (how each run
> ended), a ServiceNow service desk's tickets, GitLab.com's production incidents (its responders'
> labels) and public prompt-injection benchmarks. The rest come from **semi-synthetic** incidents:
> real log lines from the public Loghub samples, composed into incidents by ARIA's scenario builder,
> which show how ARIA behaves on that data, not how accurate it is on your production incidents. See
> [Limitations](#limitations) and the [data card](docs/data-card.md).

## What happens to an incident

1. **Intake.** An Alertmanager, Grafana or generic webhook, the periodic log scan, the console,
   the CLI, or another agent (over A2A or AG-UI) starts a run. Alerts that share a group key
   within five minutes join one run, so an alert storm becomes one incident.
2. **Parse.** Lines are redacted (secrets removed, IP and e-mail addresses pseudonymised),
   checked for prompt injection, and grouped into templates with Drain. Large inputs fan out
   over parallel shards. The parser also follows each unit of work it can name (an HDFS block, a
   task attempt, a VM boot) from start to finish, learns from the window which steps always come
   in equal numbers, and flags units that stop partway: failures that log no error at all.
3. **Severity.** Rules give a floor. A calibrated model gives probabilities and a conformal
   prediction set. An LLM may adjudicate, but only between the labels in that set.
4. **Investigate and retrieve.** An investigator tests hypotheses with read-only log tools.
   Hybrid search (BM25 plus embeddings) finds the three most similar past incidents and the
   matching runbooks. Weak evidence triggers a replan: wider retrieval, more context, another
   pass.
5. **Report.** A grounded draft, an optional LLM narrative, a critic and a final validator. Any
   claim that does not cite an existing evidence ID is repaired or replaced by the deterministic
   draft.
6. **Review.** The run pauses. A reviewer approves, edits or rejects. Nothing outbound (Slack,
   Teams, ticket drafts) happens before approval.
7. **Learn.** Approved reports join incident memory. Reviewer corrections go to a feedback
   queue, and once enough gather, the severity model's prediction sets are recalibrated on them.

![A recorded run on the console's How ARIA works page: the HDFS log on the left, with the lines behind evidence E2 lit up, and the triage tag on the right, whose claims each cite evidence IDs.](docs/images/replay.webp)

*One recorded run, with a language model doing the investigation, the report and the messages.
Pointing at a citation on the tag lights up the log lines behind it.*

## Architecture

```mermaid
flowchart LR
  subgraph In["Ways in"]
    W["Alert webhooks<br/>Alertmanager, Grafana, generic"]
    S["Log scan<br/>(tails files)"]
    U["Console (Next.js)"]
    C["CLI"]
    A["Other agents<br/>A2A, AG-UI"]
  end
  subgraph API["FastAPI service"]
    R["REST + SSE<br/>API keys, rate limits"]
    Q[("Runs, events,<br/>checkpoints, memory<br/>SQLite or Azure SQL")]
  end
  subgraph G["LangGraph triage graph"]
    P[plan] --> PS["parse_shard ×N<br/>(Send fan-out)"] --> M[merge]
    M --> SV[severity] & RC[recall]
    SV & RC --> I[investigate] --> AS{assess}
    AS -- "weak evidence" --> WD[widen] --> I
    AS --> RP["report<br/>+ critic"] --> CM[comms] --> RV{{"review<br/>(interrupt)"}}
    RV -- approve or edit --> PB[publish] --> L["learn: memory,<br/>feedback queue"]
    RV -- reject --> RJ[reject]
  end
  T["MCP tools (read-only)<br/>logs, incidents, runbooks, tickets"]
  LLM["LLM router<br/>Gemini → Gemini Lite → NIM → Azure → OpenAI-compatible → offline"]
  X["External MCP clients"] --> T
  W & S & U & C & A --> R --> G
  G <--> Q
  I & RC --> T
  SV & I & RP & CM -.-> LLM
```

Every node checkpoints, so any run can be inspected step by step, replayed or forked from an
earlier checkpoint. The design decisions behind the diagram are in [docs/adr](docs/adr/README.md).

## Quickstart

You need Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 22.13+ with pnpm for the web
app.

### Offline, no keys

```bash
make install
```

```bash
uv run aria db upgrade && uv run aria seed
```

```bash
make dev
```

Open http://localhost:3000 for the home page, then **Open the console**. New to ARIA? The
console's **How ARIA works** explains it in five short pages, and its **Guide** page replays a
real incident (ten minutes of a real Hadoop cluster's log) or starts a sample triage in one click,
and explains how to read a run. A replayed run shows the blocks ARIA flagged next to the label
Hadoop experts gave each one, and the run page's first tab tells the run as each agent's turn. In
the console, Ctrl or ⌘ + K opens search, which jumps to any page, recent incident, sample, runbook
or definition, and `?` lists the keyboard shortcuts. The API listens on
http://127.0.0.1:8000 (OpenAPI docs at `/docs`). If those ports are taken,
`make dev API_PORT=8010 WEB_PORT=3010` moves both.

Without downloaded data, ARIA seeds incident memory from the small test fixtures.
`uv run aria data download --source loghub-2k` fetches the Loghub samples (pinned commit, checked
hashes) that realistic memory and `make eval-smoke` need. `make data` downloads every source in
[data/manifest.yaml](data/manifest.yaml) for `make eval`: about 1 GB, including the full BGL log,
and it pages through GitLab's issues API.

Triage from the command line, no server needed:

```bash
uv run aria triage --scenario bgl.kernel_panic --approve
```

### With Docker

```bash
make up
```

This builds the api, worker and web images, migrates and seeds once, and waits until everything
is healthy. Then open http://127.0.0.1:3000. `make smoke` sends a run through the stack, approves
it and checks the console reads it back. `make down` stops it.

### With Gemini

1. Create a key in [Google AI Studio](https://aistudio.google.com) under **API keys**.
2. Put it in a git-ignored `.env` at the repo root: `cp .env.example .env`, then set
   `GEMINI_API_KEY=` to the key (`gemini_api_key` in lower case works too).
3. Check the key, the endpoint and the model IDs:

   ```bash
   uv run aria providers check gemini
   ```

Every agent role now tries Gemini first: `gemini-3.6-flash`, then `gemini-3.5-flash-lite` when
the first is busy or reaches its limit, then hosted NIM if its key is set. On the free tier,
Google may use what it is sent to improve its products. ARIA sends only redacted, fenced
evidence, but use a paid key, a self-hosted NIM or offline mode where even that is not
acceptable.

### With NVIDIA NIM

1. Sign in at [build.nvidia.com](https://build.nvidia.com), open a model page and choose
   **Get API Key** (keys start with `nvapi-`).
2. Put it in a git-ignored `.env` at the repo root: `cp .env.example .env`, then set
   `NVIDIA_API_KEY=` to the key.
3. Check the key, the endpoint and the model IDs:

   ```bash
   uv run aria providers check nim
   ```

Every agent role (adjudicator, investigator, reporter, critic, comms and Ask ARIA) now tries NIM,
after Gemini if that key is set too. To use your own GPUs, point `NVIDIA_NIM_BASE_URL` at a
self-hosted NIM, or start the `nim` compose profile and set `NIM_LOCAL_BASE_URL` and
`NIM_LOCAL_CHAT_MODEL` to the model it serves (see [compose.yaml](compose.yaml)). A self-hosted
NIM leads every chain.

### Send a sample alert

```bash
curl -sS http://127.0.0.1:8000/api/v1/alerts/alertmanager \
  -H 'Content-Type: application/json' \
  -d '{"version":"4","groupKey":"demo","status":"firing",
       "commonLabels":{"job":"bgl","severity":"critical"},
       "alerts":[{"status":"firing","fingerprint":"demo-1",
                  "labels":{"alertname":"KernelPanic","job":"bgl","severity":"critical"},
                  "annotations":{"summary":"Kernel panics on compute nodes"},
                  "startsAt":"2026-10-29T03:00:00Z"}]}'
```

The run appears in the console's incident queue, streams its steps live, and waits for your
review. To have ARIA read log files as well, set `ARIA_SCAN_SOURCES` (for example
`bgl=/var/log/bgl.log`) and `ARIA_SCAN_INTERVAL_S`: each burst of errors opens a run with those
lines. With `ARIA_ENV=prod`, every call needs an API key from `ARIA_API_KEYS`.

## Ways in and out

![The console's run view: an HDFS incident rated SEV3 and waiting for review, with its steps, the severity panel's probabilities and prediction set, and the messages that will be sent only on approval.](docs/images/run.webp)

| Surface | Where | What it is for |
|---|---|---|
| Console | `web/`, http://localhost:3000/console | Queue, live run view with rule trace, prediction set, evidence and cited report; review, time travel, Ask ARIA, evals, memory, settings, a guide with one-click samples, and search with keyboard shortcuts |
| REST and SSE | `/api/v1/*`, [docs/openapi.json](docs/openapi.json) | Runs, live event stream, report (JSON and Markdown), postmortem draft, review, resending a failed message, history, fork |
| Alert webhooks | `/api/v1/alerts/alertmanager`, `/grafana`, `/alerts` | Turn alert storms into one grouped run |
| Log scan | `ARIA_SCAN_SOURCES`, `ARIA_SCAN_INTERVAL_S` | Open a run on an error burst no alert caught |
| CLI | `uv run aria --help` | Triage a file or scenario, train, evaluate, check providers, run the worker |
| MCP | `/mcp` (streamable HTTP) or `make mcp` (stdio) | Read-only tools over logs, incidents, runbooks and ticket history, plus resources and prompts, for any MCP client |
| A2A | `/.well-known/agent-card.json`, `/a2a` | Other agents delegate triage; review maps to the `input-required` task state |
| AG-UI | `/agui` | The event stream the console's chat uses; works with CopilotKit |
| Ask ARIA | `/api/v1/ask` | Questions about one run's evidence, answered with citations |
| Notifications | `SLACK_WEBHOOK_URL`, `TEAMS_WEBHOOK_URL` | Posted only after a reviewer approves; a failed delivery can be sent again from the run page |
| Metrics and traces | `/metrics`, OTLP | Prometheus metrics; OpenTelemetry GenAI traces to Phoenix, Langfuse, Jaeger or Azure Monitor |

The repo also ships an [Agent Skill](skills/aria-triage/SKILL.md) that teaches other agents to
drive ARIA, an [AGENTS.md](AGENTS.md) for coding agents, and an [llms.txt](llms.txt).

## LLM providers

Providers are switched in [config/aria.yaml](config/aria.yaml), and keys come only from the
environment or Key Vault. Each role has a fallback chain, and a provider without a key is skipped.
A circuit breaker opens on repeated failures, or for as long as a rate-limited provider asks, and
per-run budgets (tokens, cost, latency, steps, tool and LLM calls) degrade a run to the rules-only
path rather than failing it.

| Provider | Default models | Status |
|---|---|---|
| Google Gemini (`gemini`) | chat `gemini-3.6-flash`, reasoning minimal | Verified with live calls on 2026-10-30, including a full triage |
| Google Gemini, lighter model (`gemini-lite`) | chat `gemini-3.5-flash-lite` | Verified with live calls on 2026-10-30 |
| NVIDIA NIM, hosted (`nim`) | chat `openai/gpt-oss-20b`; embeddings `nvidia/nemotron-3.5-embed-1b` | Verified with live calls on 2026-10-29 |
| NVIDIA NIM, second model (`nim-fallback`) | chat `minimaxai/minimax-m3.1-flash` | Verified with live calls on 2026-10-29 |
| NVIDIA NIM, self-hosted (`nim-local`) | Whatever your NIM container serves | Not verified (needs a GPU) |
| Azure OpenAI (`azure`) | Deployments `gpt-5.1` and `text-embedding-3-small`; Entra ID or key | Not verified against a live resource |
| Anthropic Claude (`claude`) | chat `claude-opus-5-5`, effort low, through Anthropic's own SDK | Not verified with a live call |
| OpenAI (`openai`) | chat `gpt-6.1-sol`, reasoning low | Not verified with a live call |
| Other OpenAI-compatible endpoints (`openai_compat`) | Your choice: vLLM, Ollama, LM Studio (`OPENAI_COMPAT_*`) | Not verified |
| Offline (`fake`, `local`) | Deterministic text; TF-IDF + SVD embeddings | Used by tests, evals and the demo |

Reranking with NIM is off until `NVIDIA_NIM_RERANK_MODEL` and `NVIDIA_NIM_RERANK_URL` are set. The
optional content-safety check (`guardrails.safety_model`, off by default) asks
`nvidia/nemotron-3.5-content-safety` on NIM. That ID is in NVIDIA's model catalog (checked
2026-10-29), but ARIA has not called it live yet, so its verdict format is unverified.
`uv run aria providers list` shows what is enabled, and `aria providers check` confirms the IDs.

## How severity is decided

| Step | What it does | Why |
|---|---|---|
| Rules | Scoring rules read component criticality, bursts and fatal markers; five floors (data risk, a crashing critical component, a critical alert, a power-supply fault, unfinished work) set a minimum | Transparent: a known-bad pattern is never rated below its floor (SEV2 or SEV3) |
| Calibrated model | Linear model on window features, temperature-calibrated | Probabilities that mean what they say |
| Conformal set | Split-conformal (LAC) set at alpha 0.10 | A label set that holds the true severity about 90% of the time on data like the calibration windows (exchangeable), less under a shift |
| LLM adjudication | Chooses only between labels already in the set | The LLM cannot invent a severity the evidence rules out |
| Policy | One label decides alone; otherwise the most severe label in the set, flagged for review | Over-triage beats under-triage when unsure |

Reviewer corrections feed recalibration: `aria train recalibrate` (and a background job, every
`severity.recalibrate_check_s`) re-fits only the conformal threshold once
`severity.recalibrate_after` new reviews have gathered. It writes `<version>-recal<n>`, keeps the
previous file, and running engines reload it. The [model card](docs/model-card.md) has the
details.

## Safety controls

- **Prompt injection.** Instruction-like log lines, alert labels and annotations are quarantined
  before any model sees them. Everything else reaches a model only as fenced, untrusted
  evidence.
- **Constrained output.** The LLM can only choose severity inside the conformal set, so injected
  text cannot change it. Every report claim must cite evidence, and the validator rejects
  anything else.
- **PII and secrets.** The parser redacts them before analysis, tool storage or any model call.
  IP and e-mail addresses are pseudonymised with a per-run keyed hash, so one host keeps one
  name within a run but cannot be linked across runs. Set the key with `ARIA_PSEUDONYM_KEY`;
  without it, ARIA keeps a random key in its database.
- **Tools.** MCP tools are read-only and allowlisted. Each run has a tool budget, and every call
  is audited.
- **Outbound actions.** Every post or ticket draft waits for human approval.
- **Access.** Named API keys, compared in constant time, plus a per-caller rate limit. Every key
  has full access: there are no read-only keys yet. The web app keeps the key in an HttpOnly
  cookie behind its own proxy, so it never reaches browser JavaScript.
- **Optional guardrail.** A content-safety model check that fails closed back to the
  deterministic draft.

The full analysis, with the code and test for each control, is in the
[threat model](docs/threat-model.md).

## Measured results

![The Hadoop cluster test on the console's Test results page: ARIA's result against the label experts gave each storage block, its precision, recall and false alarms, and a table comparing ARIA with four standard detectors, its severity engine and a keyword rule.](docs/images/real.webp)

*The Hadoop cluster test on the console's Test results page. Every number on it comes from `docs/eval-results.json`.*

<!-- generated:results -->
Generated by `make eval` at commit `c6d459d`; do not edit by hand. Apart from the real-data results, the data is **semi-synthetic**: real lines from the public Loghub samples, composed into incidents by ARIA's scenario builder, on held-out seeds 41, 42. These numbers show how ARIA behaves on that distribution, not its accuracy on production incidents.

**Real logs, expert labels**: on a real Hadoop cluster's log (more than 200 nodes, every storage block labelled by Hadoop experts), ARIA's lifecycle check flagged 151 of the 5,435 blocks it judged, 98.0% of them real failures (3 false alarms among 5,186 healthy blocks): 59.4% of the 249 failures it judged, 47.3% of all 313 in the sample. It matches or beats each standard detector on the same blocks, though they see the whole sample at once: PCA (Xu et al. 2009) finds 37.0% with 2 false alarms, an isolation forest finds 56.2% with 14 false alarms, and a rule that flags rare step counts ties it. An offline replay of the check, not of the deployed log scan.

**Real severity**: on all 7,346 20-minute windows of a supercomputer's 214.7-day log, labelled by its administrators' alert tags, ARIA rated 64 of the 680 SEV1-2 windows as SEV3-4 and paged on 512 of 6,533 quiet windows (ARIA's rules alone: 26 and 251; the highest log level: 0 and 505); accuracy 87.2% (86.5–87.9%), macro-F1 0.581.

**Real severity**: on all 3,114 20-minute windows of a second supercomputer's 47.5-day log, labelled by its administrators' alert tags, no window was labelled SEV1-2, and ARIA paged on 2,329 of 2,979 quiet windows (ARIA's rules alone: 2,186; the highest log level: 2,912); accuracy 1.5% (1.1–2.0%), macro-F1 0.010.

**Real failed jobs**: of 44 Hadoop jobs with a failure injected, ARIA flagged 30 (52.4–81.4%), and 5 of 11 healthy jobs; a rule on ERROR lines flags 19 and 2.

**Real injected bugs**: of 480 OpenStack runs that failed after a bug was injected into the code, ARIA flagged 479 (98.8–100.0%), including all 84 that no API error reported, and all 431 runs that did not fail: it was unsure of 865 of the 911 runs and sent them to a reviewer. Paging only at SEV1-2, it caught 444 failed and 133 healthy runs, where a rule on ERROR lines flags 439 and 113; ranking failed above healthy runs, it scores AUROC 0.777 (0.746–0.806), against 0.829 for counting ERROR lines.

**Build failures**: on 756 failed CI builds, a kind of log ARIA was never tuned on, the lines it kept as evidence held the lines a person marked as the cause in 41.5% of builds (38.0–45.1%); the same number of the log's last error-looking lines held them in 44.2%.

**Real tickets**: on the newest 3,737 of 24,918 tickets from a ServiceNow service desk, ARIA's priority matched the final priority for 98.5% (98.1–98.9%), the same as the impact x urgency matrix it learns, and its SLA model ranks breaches at AUROC 0.769 (0.751–0.785), against 0.737 for the best single field.

**Real incidents**: asked from its title alone, ARIA's incident memory put a past GitLab.com incident on the same service among the first three for 40.9% (38.4–43.5%) of 1,508 later incidents, against 10.7% at random. BM25 alone did better, at 44.1%: the offline embeddings it fuses in cost recall here.

**Real post-mortems**: from its title and summary of impact, ARIA's incident memory put a past AWS, Azure or Google Cloud incident with the same specific root cause among the first three for 56.6% (46.6–66.2%) of 106 later incidents, against 53.8% at random; a past incident fixed the same way, for 53.4% (at random: 52.6%).

**Severity**, 330 held-out windows:

| Method | Accuracy (95% CI) | Macro-F1 | SEV1/2 rated SEV3/4 |
|---|---|---|---|
| ARIA policy (offline) | 90.3% (87.3–93.3%) | 0.880 | 3.5% |
| TF-IDF + logistic regression (raw text) | 84.5% (80.9–88.2%) | 0.827 | 14.0% |
| Rules only | 58.2% (52.7–63.6%) | 0.524 | 22.8% |
| Keyword categories only | 41.2% (36.1–46.4%) | 0.396 | 18.4% |
| Majority class | 36.7% (31.5–41.8%) | 0.134 | 100.0% |

- Calibration: ECE 0.027. Conformal prediction sets hold the true severity in 91.2% of windows (target 90.0%), with 1.021 labels on average.
- Automation: 83.0% of windows are decided without review, at 96.0% accuracy; the rest go to a reviewer.

**End to end**, 60 offline runs through the whole graph: 100.0% of reports pass validation and 100.0% cite existing evidence for every claim; similar incidents Recall@3 100.0%; time to review p50 0.55 s, p95 1.14 s.

**With a live LLM** (Google Gemini, 3 runs at commit `53522c7`): the LLM wrote 3 of the 3 reports, and 100.0% cite evidence for every claim; time to review p50 47.2 s, mostly waiting on the provider (LLM call p50 3.0 s).

**Log parsing**: grouping accuracy 0.868 against Loghub's labelled templates (32,000 lines, 16 systems), and 0.765 on GAIA's 140,000 labelled lines from 14 systems: 0.801 on the 5 that ARIA has no format or settings for.

**Prompt injection**: the guard quarantined 97.2% of 1,000 attacks (an upper bound: the detector was tuned on this corpus) and 0.0% of 1,000 benign inputs. With 3 injected lines in each of 16 incident windows, severity was unchanged in 100.0% and tool calls in 100.0%.

**Prompt injection, public benchmarks**: of 2,654 attacks from 6 public benchmarks the detector was never tuned on, it caught 29.9% (28.1–31.7%); it flagged 3.5% of 339 benign look-alikes and 0 of 5,247,088 real log lines. Fencing, the prediction set and approval do not rely on it.

Every section, with its method: [docs/evaluation.md](docs/evaluation.md).
<!-- /generated:results -->

## Limitations

- **The lifecycle check is measured on one system.** The check that finds units of work that
  stop partway was evaluated on one HDFS sample, and its labels say whether a block failed, not
  how severe the incident was. The check's settings were chosen on this log with its labels
  in view, each system needs its unit names in `config/flows.yaml`, and the other unit kinds
  (task attempts, containers, VM instances) are untested. Every failure ARIA missed there takes
  exactly the step counts of a common healthy pattern, so step counts alone cannot set it apart.
- **The log scan opens runs on error bursts only.** It scores ERROR and FATAL lines, so a log
  that fails silently, like the HDFS sample, does not open a run on its own: its broken units
  are found when a run reads the window (from the console, the API, the CLI or a webhook). Making
  a broken unit open a run, over a window long enough to judge it, is future work.
- **The severity data is semi-synthetic.** Every split draws on the same public 2,000-line samples, so
  test windows reuse messages and templates seen in training, and templates repeat more than in
  a real fleet. Labels come from the BGL alert-tag rubric and from a scenario policy written for
  this project. Outside BGL, the policy labels a window by its true node count and peak error
  rate, which ARIA's features estimate. That suits ARIA better than real on-call labels would.
  See the [data card](docs/data-card.md).
- **The severity model learned from semi-synthetic windows.** On the real BGL log, the rules
  alone did better than the rules and model together
  ([evaluation](docs/evaluation.md#real-logs-a-supercomputers-alert-tags)). A deployment should
  recalibrate on its own reviewed incidents (`aria train recalibrate`).
- **ARIA knows few failure modes outside its samples.** On OpenStack runs with an injected bug,
  its one OpenStack failure mode is a missing image-cache file, from a 2,000-line sample of
  another deployment. It was unsure of most runs and sent them to a reviewer at the most severe
  label in their prediction set, so at SEV1-3 it flags nearly every run, failed or not. Ranked by
  its probability of SEV1-2, it tells failed from healthy runs a little less well than counting
  ERROR lines does ([evaluation](docs/evaluation.md#real-failures-bugs-injected-into-openstack)).
  A deployment needs failure modes and reviewed incidents of its own.
- **Memory needs more than a summary of impact.** On three clouds' public post-mortems, no
  method finds a past incident with the same root cause or fix from an incident's title and
  impact summary much more often than picking past incidents at random does
  ([evaluation](docs/evaluation.md#real-incidents-three-clouds-post-mortems)).
- **Some sources and suites are missing.** Zenodo, Hugging Face, figshare and UCI's own site were
  unreachable when these results were produced. ARIA fetches the BGL, Hadoop and UCI data from
  copies pinned by checksum or commit. Zenodo and Hugging Face became reachable later: the full
  HDFS log, Loghub-2.0's labelled templates and LogChunks are recorded in the
  [data card](docs/data-card.md#found-later-for-the-next-round) for the next round. The brief's
  LLM-only severity baseline and per-provider cost comparison have no results yet.
- **The injection detector is a first line, not a wall.** On public benchmarks it was never
  tuned on, it misses most attacks phrased as ordinary requests
  ([evaluation](docs/evaluation.md#prompt-injection-public-benchmarks)). Fencing, the prediction
  set and approval are what stop a missed line from acting. Azure Prompt Shields is not
  integrated.
- **The offline investigator is simple.** It tests hypotheses with transparent checks. Real
  incidents with several overlapping causes will be harder than the scenarios.
- **Live LLM runs are few.** The live numbers come from a handful of runs on Gemini's free tier.
  Its first model was often busy that day, so the lighter one answered most calls. Production
  quality and latency depend on your provider and plan.
- **Some providers are untested live.** Azure OpenAI, self-hosted NIM, OpenAI-compatible
  endpoints and the NIM content-safety model have contract tests against mocked HTTP but have
  not been called live.
- **The cost budget needs prices.** No shipped provider config sets token prices, so the
  per-run cost limit never binds. The token, latency, step and call limits do.
- **A few things are single-instance.**
  - The rate limiter and A2A task records live in memory, so A2A clients lose track of tasks on
    a restart. The run itself survives and can be reviewed over REST.
  - Run the log scan in one process only: replicas that each scan the same files can open
    duplicate runs.
- **The graph is flat.** It is one LangGraph graph of specialist nodes, not nested subgraphs
  (see [ADR 0001](docs/adr/0001-one-langgraph-graph-of-specialist-nodes.md)).
- **Two parts of the brief are not built.**
  - The planner replans when retrieval is weak or no hypothesis forms, but not when a report
    fails validation or severity confidence is low: those runs go to the reviewer as they are.
  - The AG-UI endpoint sends a full state snapshot after each step, never a JSON Patch delta.
    Clients get the same state, with more bytes per update.
- **Raw log lines are kept with their run.** Analysis, model calls, reports, messages and memory
  use redacted text, but the lines a run was sent stay in its stored request and checkpoints, so
  it can be replayed, until the run is deleted. Nothing prunes old runs yet.
- **Mobile Lighthouse is at or just under the brief's bar.** On mobile, the landing page's
  performance score sits at or a few points below the brief's target of 95, varying from run to
  run; `make web-lighthouse` prints it, and CI gates at 90. Desktop and the other categories meet
  their bars.
- **The UI components are written in this repo,** in the shadcn/ui pattern, rather than pulled
  from the shadcn, 21st.dev or React Bits registries, which could not be reached when they were
  built.

## Development

| Command | What it does |
|---|---|
| `make install` | Python (all groups and extras), web and video dependencies |
| `make lint` | ruff format check, ruff lint, mypy `--strict` |
| `make test` | pytest with the 80% coverage gate (`make test-fast` skips slow tests) |
| `make eval` | Every evaluation suite; rewrites [docs/evaluation.md](docs/evaluation.md) and the results above |
| `make eval-smoke` | The CI regression gate against [config/eval_thresholds.yaml](config/eval_thresholds.yaml) |
| `make web-check` | Prettier, ESLint, TypeScript and Vitest for `web/` |
| `make web-e2e` | Playwright and axe (WCAG 2.2 AA) against an offline API |
| `make web-lighthouse` | Lighthouse bars, median of three runs per page |
| `make audit` | pip-audit, actionlint, zizmor |
| `make video` | Render the explainer video with Remotion to `video/out/aria-demo.mp4` |
| `make openapi` | Re-export the API schema and regenerate the web client types |
| `make help` | Everything else |

Tests and evals run offline with the fake provider. CI runs lint, types and tests, the eval gate,
the web checks with Playwright and Lighthouse, dependency and workflow audits, the Bicep build
and the image builds, and renders the explainer video (uploaded as the `aria-demo` artifact). See
[.github/workflows/ci.yml](.github/workflows/ci.yml).

## Deploying to Azure

For a free public demo instead (the website on Vercel, the API on Render), follow
[Deploy a free public demo](docs/deploy-free.md).

```bash
azd env set ARIA_API_KEYS "ops:<a long random secret>"
```

```bash
azd env set ARIA_PSEUDONYM_KEY "<another long random secret>"
```

```bash
azd up
```

After the first deploy, seed incident memory once:

```bash
az containerapp job start -g "$(azd env get-value AZURE_RESOURCE_GROUP)" -n "$(azd env get-value ARIA_SEED_JOB)"
```

[infra/](infra/main.bicep) provisions three Container Apps (api, worker, web) and that one-off
seed job. It also creates Azure SQL, Key Vault for secrets, a container registry, Log Analytics with
Application Insights, and a user-assigned managed identity. Azure OpenAI is optional. The
[deploy workflow](.github/workflows/deploy.yml) runs the same steps from GitHub Actions with OIDC,
on manual trigger only. Day-two operations are in the [ops runbook](docs/ops-runbook.md).

## Repository layout

| Path | What lives there |
|---|---|
| `src/aria/graph/` | The LangGraph workflow, state and runner |
| `src/aria/agents/` | The investigator agent and its tools |
| `src/aria/parsing/`, `src/aria/security/` | Drain parsing, redaction, injection guard, content safety |
| `src/aria/severity/` | Rules, model, conformal sets, recalibration |
| `src/aria/retrieval/`, `src/aria/mcp/` | Hybrid search, embeddings, the MCP server |
| `src/aria/reporting/` | Report writer, critic, validator, comms drafts |
| `src/aria/llm/` | Providers, router, budgets, circuit breakers, prompts |
| `src/aria/api/` | FastAPI app, webhooks, log scan, A2A, AG-UI, worker |
| `src/aria/evals/` | Evaluation suites and the report generator |
| `web/` | Next.js landing page and console |
| `video/` | The Remotion explainer, built from one recorded run and the measured results |
| `runbooks/` | The runbook library ARIA retrieves from |
| `models/` | The exported severity model and offline embeddings |
| `data/manifest.yaml` | Dataset sources, pinned commits and checksums (raw data is never committed) |
| `infra/`, `compose.yaml`, `Dockerfile` | Deployment |

## Data and licences

ARIA's code is under the [MIT licence](LICENSE). The datasets keep their own licences and are
downloaded, never committed:

- [Loghub](https://github.com/logpai/loghub) is free for research and academic work. Cite J. Zhu,
  S. He, P. He, J. Liu, M. R. Lyu, "Loghub: A Large Collection of System Log Datasets for
  AI-driven Log Analytics", ISSRE 2023.
- The UCI [Incident management process enriched event log](https://doi.org/10.24432/C57S4H) is
  under CC BY 4.0.
- The prompt-injection benchmarks (BIPIA, CyberSecEval 2, NotInject, Giskard's collection, the
  in-the-wild jailbreaks) are MIT-licensed; InjecAgent and Tensor Trust state no licence and are
  read only to evaluate. [`data/manifest.yaml`](data/manifest.yaml) lists what to cite for each.
- GitLab.com's [production incidents](https://gitlab.com/gitlab-com/gl-infra/production/-/issues)
  are public issues with no licence stated. ARIA reads them through GitLab's API only to evaluate
  incident memory, and never redistributes them.

The small fixtures under `tests/fixtures/` are excerpts of the Loghub samples, including a
ten-minute cut of the real HDFS log (with its experts' labels) that the console replays. Cite W.
Xu, L. Huang, A. Fox, D. Patterson, M. I. Jordan, "Detecting Large-Scale System Problems by
Mining Console Logs", SOSP 2009, for the HDFS labels. Sources and pinned checksums are in
[data/manifest.yaml](data/manifest.yaml).

## Docs

- [Evaluation](docs/evaluation.md): every measured number and how it was measured
- [Architecture decisions](docs/adr/README.md)
- [Data card](docs/data-card.md)
- [Model card](docs/model-card.md)
- [Threat model](docs/threat-model.md)
- [Ops runbook](docs/ops-runbook.md)
- [Deploy a free public demo](docs/deploy-free.md): the website on Vercel, the API on Render
- [Quality audit](docs/quality-audit.md): what the pre-release audit checked, fixed and left
- [Build brief](docs/build-brief.md): the specification and its acceptance checks
- [AGENTS.md](AGENTS.md): conventions for coding agents working on this repo
