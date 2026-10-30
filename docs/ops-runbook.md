# Ops runbook

This runbook is for whoever deploys and operates ARIA: how to run it, configure it, watch it, change it and fix it.

It is not the incident runbook library in [`runbooks/`](../runbooks), which ARIA itself retrieves and cites in its reports. The security reasoning behind several steps here is in the [threat model](threat-model.md). The commands assume the repository root as the working directory.

## What runs

| Component | Command | What it does |
|---|---|---|
| API | `aria serve` (`make api`) | Serves REST and server-sent events, MCP at `/mcp`, A2A at `/a2a` and AG-UI at `/agui`, and the health checks. With `ARIA_WORKER_MODE=inprocess` it also executes runs and the periodic jobs. |
| Worker | `aria worker` (`make worker`) | With `ARIA_WORKER_MODE=external`, it claims queued runs from the database and executes them, and runs the periodic jobs (the log scan and recalibration) |
| Web app | `pnpm --dir web dev` (`make web`), or the `web` image | The landing page and the console. Its server forwards console requests to the API with the signed-in key. |
| Database | | SQLite by default, or Azure SQL. It holds runs, checkpoints, events, reports, outbound actions, the tool-call audit, reviews and incident memory. |
| Model files | | The trained severity model, `models/severity_log.json`, ships with the code. Recalibrated versions and the offline embeddings live in `ARIA_MODELS_DIR` (`/var/lib/aria/models`, on the shared volume, in containers). |
| Optional | | Arize Phoenix for traces, and a self-hosted NVIDIA NIM (both are compose profiles) |

Review decisions can go to any API process, because checkpoints live in the shared database; the process that receives a decision publishes the report and sends approved messages.

## Deploy

### Local

```bash
make install
```

```bash
cp .env.example .env
```

```bash
uv run aria db upgrade && uv run aria seed
```

```bash
make dev
```

The API listens on http://127.0.0.1:8000 and the web app on http://localhost:3000; `make dev API_PORT=8010 WEB_PORT=3010` moves both. `aria seed` does three things:

- loads the runbooks;
- seeds incident memory with synthetic incidents, labelled as synthetic;
- fits the offline embeddings.

It uses the small Loghub samples in `tests/fixtures/loghub` unless `make data` has downloaded the full set. With no provider key, LLM steps fall back to the deterministic offline provider. The severity adjudicator has no offline fallback, so when a severity needs adjudication, the conservative policy decides instead: it picks the most severe class in the prediction set and flags the run for review.

### Docker compose

```bash
make up
```

```bash
make smoke
```

`make up` runs `docker compose up -d --wait`, which starts four services:

| Service | Address | Role |
|---|---|---|
| `init` | | Migrates the database, seeds memory once, then exits |
| `api` | 127.0.0.1:8000 | The API |
| `worker` | | `ARIA_WORKER_MODE=external` |
| `web` | 127.0.0.1:3000 | The web app |

The services share the `aria-data` volume (`/var/lib/aria`). `make smoke` triages one synthetic run through the worker to the review pause, approves it, and checks that the report is published and that the console serves it.

Things to know:

- **API keys.** Compose defaults to `ARIA_ENV=dev`, so the API needs no key. Set `ARIA_ENV=prod` and `ARIA_API_KEYS` before exposing it beyond your machine. When keys are set, give the smoke script one in `ARIA_API_KEY`.
- **Variables.** Compose passes only the variables listed under `x-aria-env` in [`compose.yaml`](../compose.yaml). Add any others, such as log scan sources, webhook URLs or model overrides, in a `compose.override.yaml`.
- **Traces.** Run `ARIA_OTEL_EXPORTER=otlp docker compose --profile observability up -d --wait` to add Phoenix at http://127.0.0.1:6006.
- **Self-hosted NIM.** The `nim` profile needs an NVIDIA GPU, `NGC_API_KEY`, `NIM_IMAGE`, `NIM_LOCAL_BASE_URL=http://nim:8000/v1` and `NIM_LOCAL_CHAT_MODEL`. Once set, `nim-local` leads every provider chain.
- **TLS-inspecting proxies.** Behind one, build with the proxy's CA as a build secret, as the [`Dockerfile`](../Dockerfile) header shows. No image layer keeps it.

`make down` stops the stack.

### Azure

`azd up` provisions [`infra/`](../infra) and deploys three images. It provisions:

- Container Apps: api, worker, web and a seed job;
- Azure SQL: serverless, with Entra ID sign-in only;
- Key Vault;
- a container registry;
- Log Analytics and Application Insights;
- one user-assigned managed identity;
- optionally, Azure OpenAI.

Before the first run, set the secrets:

```bash
azd env set ARIA_API_KEYS "ops:<a long random secret>"
```

```bash
azd env set ARIA_PSEUDONYM_KEY "<another long random secret>"
```

```bash
azd env set GEMINI_API_KEY "<key from aistudio.google.com>"
```

```bash
azd env set NVIDIA_API_KEY "<key from build.nvidia.com>"
```

`GEMINI_API_KEY` and `NVIDIA_API_KEY` are optional. Then deploy, and seed incident memory once:

```bash
azd up
```

```bash
az containerapp job start -g "$(azd env get-value AZURE_RESOURCE_GROUP)" -n "$(azd env get-value ARIA_SEED_JOB)"
```

Optional settings:

- `ARIA_DEPLOY_OPENAI`, with `AZURE_OPENAI_CHAT_MODEL` and `AZURE_OPENAI_CHAT_MODEL_VERSION`, adds an Azure OpenAI deployment.
- `ARIA_SQL_FREE_OFFER` picks the Azure SQL free offer (on by default). The worker polls the database every few seconds, so a serverless database never sits idle long enough to auto-pause, and the offer's monthly free vCore-seconds last about two and a half days. After that, with `ARIA_SQL_FREE_LIMIT=AutoPause` (the default, no charge), the database stays paused until the next month and ARIA stops; `ARIA_SQL_FREE_LIMIT=BillOverUsage` keeps it running and bills the excess. For anything longer than a demo, choose one of those, or set `ARIA_SQL_FREE_OFFER=false`.
- `make bicep` compiles the templates first.
- The manual [Deploy to Azure](../.github/workflows/deploy.yml) workflow does the same as `azd up`, through OpenID Connect. Its header lists the GitHub environment variables and secrets it needs.

How the Azure deployment is set up:

- **Ingress.** The API and the web app have public HTTPS ingress, and the API requires keys (`ARIA_ENV=prod`).
- **Migrations.** The API runs one replica with `ARIA_MIGRATE_ON_START=true`, so migrations run as it starts.
- **Replicas.** The worker and the web app each run one to three replicas.
- **Secrets.** Apps read their secrets from Key Vault with the managed identity.

## Configuration

Settings come in two layers:

- **Environment variables** (`ARIA_*`, plus the provider variables) for deployment facts and secrets. Locally they can live in `.env`; on Azure, in Key Vault.
- **[`config/aria.yaml`](../config/aria.yaml)** for behaviour: provider chains, budgets, guardrails, retrieval and triggers. String values can reference environment variables as `${NAME:-default}`, and the file never holds a secret.

Both are read when a process starts, so restart after a change. `GET /api/v1/settings` shows the limits, guardrails and routing in force, and never any secrets.

| Variable | What it does |
|---|---|
| `ARIA_ENV` | `dev`, `test` or `prod`. `prod` refuses to start without API keys and never uses the offline fake provider. The images default to `prod`; compose sets `dev`. |
| `ARIA_API_KEYS` | Comma-separated `name:secret` pairs. The name labels the caller in logs, in review records and for rate limiting. Every valid key can do everything, including reviews. |
| `ARIA_DATABASE_URL` | SQLAlchemy URL: SQLite by default, or Azure SQL through `mssql+pyodbc` |
| `ARIA_DATABASE_AUTH` | `default`, or `entra` to sign in to Azure SQL with the managed identity |
| `ARIA_WORKER_MODE` | `inprocess` (the API executes runs) or `external` (`aria worker` executes them) |
| `ARIA_WORKER_CONCURRENCY` | Runs executed at once: by the API in `inprocess` mode, and by each `aria worker` unless `--concurrency` overrides it |
| `ARIA_MAX_BODY_BYTES` | Largest request body the API reads (48 MiB by default); bigger ones get 413 |
| `ARIA_MIGRATE_ON_START` | Run database migrations when the API starts |
| `ARIA_REQUIRE_APPROVAL` | On by default. When off, runs that also ask for no approval publish without review and send nothing outbound. |
| `ARIA_RATE_LIMIT_PER_MINUTE` | Requests per minute for each key name |
| `ARIA_CORS_ORIGINS` | Browser origins allowed to call the API directly. The console goes through its own server and does not need this. |
| `ARIA_PUBLIC_BASE_URL` | The API's public URL: an allowed host for `/mcp`, the address the A2A agent card advertises (`<url>/a2a`), and where messages link when `ARIA_CONSOLE_URL` is unset |
| `ARIA_CONSOLE_URL` | Where people open a run (the web console). Messages link to `<url>/console/runs/<run id>` when it is set. |
| `ARIA_WORKER_HEALTH_PORT` | A port where `aria worker` answers HTTP liveness probes from its heartbeat (Container Apps ignores the image's health check). Unset: no endpoint. |
| `ARIA_PSEUDONYM_KEY` | Keys the per-run pseudonyms for IP and e-mail addresses. Set the same value on every process. Without it, the processes sharing a database make one random key and keep it in that database, so they still agree, but anyone with a copy of the database can recompute the pseudonyms: set it from Key Vault in production. |
| `ARIA_LOG_LEVEL`, `ARIA_LOG_FORMAT` | Log level, and `json` or `console` output |
| `ARIA_OTEL_EXPORTER`, `ARIA_OTLP_ENDPOINT` | Trace export: `none`, `console`, `otlp` (to `ARIA_OTLP_ENDPOINT`) or `azure` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Where the `azure` exporter sends traces |
| `ARIA_OTEL_CAPTURE_CONTENT` | Record prompt and completion text in traces. Off by default, because that text holds log data. |
| `ARIA_CONFIG_FILE`, `ARIA_DATA_DIR`, `ARIA_MODELS_DIR`, `ARIA_RUNBOOKS_DIR` | Where the config file, data, offline embeddings and runbooks live |
| `ARIA_MCP_URL`, `ARIA_MCP_TOKEN` | Have the investigator call tools on a remote MCP endpoint instead of in-process |
| `GEMINI_API_KEY` (or `gemini_api_key`) | Enables Gemini for every role, ahead of hosted NIM |
| `GEMINI_CHAT_MODEL`, `GEMINI_LITE_MODEL`, `GEMINI_REASONING_EFFORT`, `GEMINI_BASE_URL` | Override the Gemini models, the reasoning effort (minimal by default) and the endpoint |
| `NVIDIA_API_KEY` | Enables hosted NVIDIA NIM for every role |
| `NVIDIA_NIM_BASE_URL`, `NVIDIA_NIM_CHAT_MODEL`, `NVIDIA_NIM_REASONING_EFFORT`, `NVIDIA_NIM_FALLBACK_MODEL`, `NVIDIA_NIM_EMBED_MODEL`, `NVIDIA_NIM_SAFETY_MODEL`, `NVIDIA_NIM_RERANK_MODEL`, `NVIDIA_NIM_RERANK_URL` | NIM endpoint and model overrides. Reranking stays off until both rerank variables are set. |
| `NIM_LOCAL_BASE_URL`, `NIM_LOCAL_CHAT_MODEL`, `NIM_LOCAL_EMBED_MODEL`, `NIM_LOCAL_RERANK_MODEL`, `NIM_LOCAL_RERANK_URL` | A self-hosted NIM, which leads every chain once its URL is set |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_USE_ENTRA`, `AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_EMBED_DEPLOYMENT` | Azure OpenAI, with a key or with the managed identity |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`, `OPENAI_EMBED_MODEL` | Any OpenAI-compatible endpoint (OpenAI, vLLM, Ollama) |
| `ARIA_SCAN_INTERVAL_S`, `ARIA_SCAN_SOURCES` | The periodic log scan: seconds between polls (`0` turns it off), and `system=path` pairs |
| `SLACK_WEBHOOK_URL`, `TEAMS_WEBHOOK_URL`, `ARIA_OUTBOUND_WEBHOOK_URL`, `ARIA_OUTBOUND_WEBHOOK_SECRET` | Destinations for approved messages, and the key that signs generic webhook deliveries |
| `ARIA_API_URL` | Web app: where its server reaches the API |
| `ARIA_WEB_URL` | Web app: its public URL, used in page metadata and link previews. Pages are prerendered, so pass it when building the image too (`--build-arg ARIA_WEB_URL=...`; azd reads it from `azd env set ARIA_WEB_URL`) |
| `ARIA_URL`, `ARIA_WEB_URL`, `ARIA_API_KEY` | `make smoke`: the stack to test, and the key to use |

The `config/aria.yaml` settings operators change most often:

| Setting | What it does |
|---|---|
| `llm.routing` | The provider chain for each role |
| `llm.safety` | The providers that answer the content-safety check |
| `budgets` | Per-run limits for tokens, cost, elapsed time, steps, tool calls and LLM calls |
| `guardrails` | Redaction, IP pseudonyms, injection detection, the content-safety check, and the line caps |
| `triggers` | The alert grouping window, plus the scan's burst threshold and window size |
| `severity.recalibrate_after`, `severity.recalibrate_check_s` | When recalibration runs. Their defaults are in [`config.py`](../src/aria/config.py), so add them to the YAML to change them. |

## Watching it run

### Health

| Check | Endpoint or command | Notes |
|---|---|---|
| API liveness | `GET /healthz` | Public. 200 while the process serves requests. |
| API readiness | `GET /readyz` | Public. 503 only when the database does not answer. `"status": "degraded"` means no real LLM is available; runs still work, deterministically. It does not check the migration revision. |
| Web liveness | `GET /api/healthz` on the web app | |
| Web view of the API | `GET /api/ready` on the web app | Forwards the API's `/readyz` |
| Worker liveness | `aria worker-health --max-age 60` | Exits 1 when the worker has not polled the queue recently. It reads this host's heartbeat file, `worker-<hostname>.heartbeat`, in `ARIA_DATA_DIR`. |
| Providers | `GET /api/v1/providers` | Each provider's models, circuit-breaker state and last error, without keys |

Two caveats about the worker check:

- **Shared volume.** Each container writes its own heartbeat file (named after its hostname), so with several workers on one volume each check still reports on its own worker.
- **Azure.** Container Apps ignores the image's HEALTHCHECK, so the worker app serves this heartbeat on port 8001 (`ARIA_WORKER_HEALTH_PORT`) and its liveness probe restarts a worker that stops polling (`infra/resources.bicep`).

### Metrics

`GET /metrics` serves Prometheus text and needs an API key. Give the scraper its own key:

```yaml
scrape_configs:
  - job_name: aria
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/aria-key
    static_configs:
      - targets: ["127.0.0.1:8000"]
```

| Metric | Meaning |
|---|---|
| `aria_runs{status}` | Runs in each state, read from the database at scrape time. States: `queued`, `running`, `awaiting_review`, `published`, `rejected`, `failed`. |
| `aria_run_events_total{kind}` | Run events by kind |
| `aria_runs_finished_total{status}` | Runs that reached a final state |
| `aria_tool_calls_total{tool}` | Investigator tool calls |
| `aria_reviews_total{decision}` | Review decisions |
| `aria_time_to_review_seconds` | From the start of a run until its report is ready for review |
| `aria_info{version}` | The running version |

Only the API process serves metrics. In `external` mode the counters and the histogram see only what the API process executes, which is reviews and publishing. `aria_runs{status}` reads the database, so it covers every process.

### Traces

Set `ARIA_OTEL_EXPORTER=otlp` and `ARIA_OTLP_ENDPOINT`, for example Phoenix in compose. On Azure, `azure` sends traces to Application Insights. Spans follow the OpenTelemetry GenAI conventions (`chat <model>`, `execute_tool <tool>`), and carry no prompt or completion text unless `ARIA_OTEL_CAPTURE_CONTENT=true`.

The API and `aria worker` both configure the exporter, so runs are traced whichever process executes them. The API's Prometheus counters cover only runs the API itself executes.

### Logs

Processes log to standard output. With `ARIA_LOG_FORMAT=json`, each line is one JSON event. On Azure, Container Apps sends them to Log Analytics, which keeps them for 30 days. Events worth an alert or a search:

| Event | Meaning |
|---|---|
| `api.open` | The API is running without API keys |
| `api.started`, `api.migrated`, `worker.started`, `worker.stopped` | Lifecycle |
| `worker.recovered` | The API continued runs that a previous process left unfinished |
| `worker.job_failed`, `runner.failed` | A run failed |
| `llm.provider_error`, `llm.invalid_output` | A provider failed, or returned output that did not validate |
| `notify.sent`, `notify.failed` | An approved message was delivered, or was not |
| `scan.started`, `scan.run_opened`, `scan.covered`, `scan.failed` | The log scan |
| `severity.recalibrated`, `severity.model_reloaded`, `severity.recalibration_failed`, `severity.model_missing` | The severity model |
| `services.ticket_models_missing` | No ticket model was found at start |

## Routine operations

### Rotate an API key

`ARIA_API_KEYS` holds `name:secret` pairs, and every valid key has full access. Two secrets may share a name, which keeps reviews and the rate-limit bucket under one label during the overlap. In production each secret needs at least 32 characters (`openssl rand -hex 32` makes one), and a secret must not contain a colon: `a:b` is read as a key named `a`. Every request to a protected path is logged as `api.request` with its method, path, status and key name (never the secret or the query string), so the log shows who read, reviewed or deleted what.

1. Add the new secret beside the old one, for example `ops:<new secret>,ops:<old secret>`, then restart the API and workers.
2. Move every client to the new secret:
   - people signed in to the console;
   - Alertmanager and Grafana;
   - MCP and A2A clients;
   - the Prometheus scraper;
   - `ARIA_API_KEY` for the smoke script.
3. Remove the old secret, then restart again. The console signs out anyone whose stored key the API now refuses.

On Azure:

1. Run `azd env set ARIA_API_KEYS "…"`, then `azd provision`, which updates the Key Vault secret. Alternatively, update the GitHub environment secret and run the deploy workflow.
2. Restart the api and worker revisions so they read the new value. To find a revision's name, run `az containerapp revision list -g <resource group> -n <app> -o table`.
3. Restart each one with `az containerapp revision restart -g <resource group> -n <app> --revision <revision>`.

Rotate provider keys (`GEMINI_API_KEY`, `NVIDIA_API_KEY` and the others) the same way: change the variable or the Key Vault secret, then restart.

### Switch or add an LLM provider

A provider is enabled when its endpoint and key are set; chains skip disabled providers, so switching takes configuration only:

| Provider | What to set |
|---|---|
| Google Gemini | `GEMINI_API_KEY` (get one at aistudio.google.com). Optionally, the model variables. |
| Hosted NVIDIA NIM | `NVIDIA_API_KEY` (keys start with `nvapi-`; get one at build.nvidia.com). Optionally, the model variables. |
| Self-hosted NIM | `NIM_LOCAL_BASE_URL` and `NIM_LOCAL_CHAT_MODEL` (or the compose `nim` profile) |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, then `AZURE_OPENAI_API_KEY` or `AZURE_OPENAI_USE_ENTRA=true`, and the deployment names |
| Any OpenAI-compatible server | `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_CHAT_MODEL` |

To change the order providers are tried in, edit `llm.routing` in `config/aria.yaml`. Then check the result:

```bash
uv run aria providers list
```

```bash
uv run aria providers check nim
```

`providers list` shows every provider, whether it is enabled and which roles use it. `providers check` verifies keys, reachability and model IDs. By default it sends one tiny chat request and one embedding request, which costs a little; pass `--no-probe` to read only the model catalog. It does not test the content-safety model. `uv run aria providers models nim` lists every model the provider serves.

Changing the embedding provider changes the vector space. Memory re-embeds stale rows when it reloads, so an index never mixes models.

### Scale workers

- **More workers.** Run more `aria worker` processes against the same database; a claim is a conditional update, so two workers never take the same run. In compose, run `docker compose up -d --scale worker=3`. On Azure, raise the worker app's `minReplicas` (the template allows up to three).
- **Concurrency.** Set `ARIA_WORKER_CONCURRENCY`, or override it per worker with `aria worker --concurrency N`.
- **The database.** SQLite serialises writes. For more than a couple of workers, use Azure SQL.
- **Abandoned runs.** Every process that drives a run, a worker or the API applying a review, claims it first and renews the claim every minute; it lets go when the run pauses or ends. A run whose holder went quiet for 5 minutes is reclaimed by another worker (or, in process, by the API), and a process with every slot busy leaves it to the others. A reclaimed run that had already paused for review, or ended, is recorded as such and let go at once. Two processes never drive one run at once, and each approved message is marked as being sent before it goes out, so it goes out once.
- **Periodic jobs.** Each worker runs the recalibration job against the shared model file; repeating it is harmless, because the same reviews give the same threshold. Configure the log scan on one worker only, or replicas tailing the same files can open duplicate runs.
- **More API replicas.** Run migrations as a separate step (`aria db upgrade`), and set `ARIA_MIGRATE_ON_START=false`. The rate limiter and the A2A task store live in each process's memory, so each replica keeps its own. Alert grouping does not: an alert storm delivered to several replicas at once still opens one group and one run. The database keeps one open group per alert key (a unique index, added by `aria db upgrade`), and every request tries the group's run IDs in the same order, so racing requests end up on the same run.

### Database migrations

```bash
uv run aria db current
```

```bash
uv run aria db upgrade
```

Apply migrations before or as a release starts:

- **Compose.** The `init` service runs `aria db upgrade` on every `make up`.
- **Azure.** The API migrates as it starts, at one replica.

There is no downgrade command, so take a backup before upgrading. To go back, restore it.

### Back up and restore

SQLite, in compose: back up the live database with Python's online backup API, then copy the copy out:

```bash
docker compose exec api python -c "import sqlite3; src = sqlite3.connect('/var/lib/aria/aria.db'); dst = sqlite3.connect('/var/lib/aria/backup.db'); src.backup(dst); dst.close()"
```

```bash
docker compose cp api:/var/lib/aria/backup.db ./aria-backup.db
```

To restore, stop the worker, copy the backup in, write it over the database through the API container (so the file keeps its owner), then restart:

```bash
docker compose stop worker
```

```bash
docker compose cp ./aria-backup.db api:/var/lib/aria/restore.db
```

```bash
docker compose exec api python -c "import sqlite3; src = sqlite3.connect('file:/var/lib/aria/restore.db?mode=ro', uri=True); dst = sqlite3.connect('/var/lib/aria/aria.db'); src.backup(dst); dst.close()"
```

```bash
docker compose restart api
```

```bash
docker compose start worker
```

Azure SQL keeps automated backups. Restore one to a new database with point-in-time restore, then point `ARIA_DATABASE_URL` at it; the variable is set in [`infra/resources.bicep`](../infra/resources.bicep). The retention depends on the tier and the offer, so check it in the portal.

What else to keep:

- **`config/aria.yaml`.** It is in git.
- **Key Vault secrets.** Soft delete and purge protection are on.
- **Recalibrated model files** are optional: ARIA rebuilds them from the reviews in the database.

### Recalibration

Approvals and edits record each run's model input and the severity the reviewer settled on. Every `severity.recalibrate_check_s` seconds (600 by default; 0 turns it off), the process that executes runs checks whether `severity.recalibrate_after` new reviews have gathered since the loaded model was calibrated (30 by default, never fewer than 10). If they have, it refits the conformal threshold on every reviewed incident. Coefficients never change.

It saves the new model to `severity_log.json` in `ARIA_MODELS_DIR` under a version such as `<trained version>-recal<n>`, and keeps the previous file beside it as `severity_log.<version>.json`. The trained model that ships with the code is never overwritten there: engines read it until the first recalibration. Running engines reload the file when its modification time changes, at the start of each run's severity step, in every container that shares the volume.

**Watch it.**

- `GET /api/v1/feedback` reports the reviews, the model version, the reviews it was calibrated on, the reviews pending, and the coverage before and after.
- The console's Settings page shows the same under "Learning from reviews".
- The log line `severity.recalibrated` records each change.

In `external` mode the workers run the job. The API checks the shared model file before it answers `/api/v1/feedback`, so it reports the version the workers wrote.

**Preview a recalibration** without saving it:

```bash
uv run aria train recalibrate --dry-run
```

It prints the coverage and mean set size before and after. `--min-new-reviews N` overrides the threshold; in compose, run it with `docker compose exec worker aria train recalibrate --dry-run`.

**Roll back.**

1. Copy the kept version over the live model in `ARIA_MODELS_DIR`, for example `cp severity_log.<version>.json severity_log.json` (in compose: `docker compose exec worker sh -c 'cd /var/lib/aria/models && cp severity_log.<version>.json severity_log.json'`). Deleting `severity_log.json` there returns to the trained model. Engines pick the change up at the next run.
2. Then set `severity.recalibrate_check_s: 0` (or raise `recalibrate_after`), and restart. The restored file counts fewer reviews, so the next check would recalibrate again.

In containers, the live model sits on the shared volume, so it survives a recreated container. In a checkout, `ARIA_MODELS_DIR` is `models/`, so a recalibration rewrites the committed model file (the previous version stays beside it).

### Enable the log scan

The scan tails log files and opens a run when the recent window's error burst score reaches `triggers.scan_min_burst_score`.

1. Set `ARIA_SCAN_INTERVAL_S` (for example `60`) and `ARIA_SCAN_SOURCES`. The sources are comma-separated `system=path` pairs, such as `hdfs=/var/log/hdfs.log,openssh=/var/log/auth.log`, where `system` is the log format.
2. Make the files readable where runs execute: the API in `inprocess` mode, each worker in `external` mode. In compose, mount them read-only into the `worker` service and add the variables to it, both in an override file.
3. Restart. Expect `scan.started` with the number of sources.

The first look at each file starts at its end, so history never opens a run. A file that shrinks (rotated or truncated) is read again from the top. Each system gets at most one scan run at a time, and none within `triggers.alert_group_window_s` of the last.

### Enable the content-safety check

1. Set `guardrails.safety_model: true` in `config/aria.yaml`. The check uses the `llm.safety` chain, which is hosted NIM, so `NVIDIA_API_KEY` must be set.
2. The model is `NVIDIA_NIM_SAFETY_MODEL`, which defaults to `nvidia/nemotron-3.5-content-safety`. That ID is in NIM's catalog (checked 2026-10-29; `uv run aria providers check nim` reports it), but ARIA has not called it live, so send it a few known-safe and known-unsafe samples and check the verdicts before relying on it.
3. Restart.

The safety model reads LLM-written report claims and polished messages. A flagged one is replaced by the deterministic draft, and run notes say why. Each check is one more LLM call against the run's budget. The check fails closed; see [the safety check flags everything](#the-safety-check-flags-everything).

### Delete a run

`DELETE /api/v1/runs/{run_id}` removes a run everywhere:

- its checkpoints, lines and events;
- its report and outbound actions;
- its tool-call audit and reviews;
- its incident-memory entry.

It answers 409 while the run is queued or running. Nothing deletes old runs automatically.

## Troubleshooting

### Runs stay queued

**Likely cause.** `ARIA_WORKER_MODE=external` with no worker running, or a worker that cannot reach the database. In `inprocess` mode, runs beyond `ARIA_WORKER_CONCURRENCY` wait for a slot.

**Check.**

- `aria_runs{status="queued"}` keeps rising.
- `GET /api/v1/settings` shows the `worker_mode`.
- `aria worker-health` exits 1.
- Compose: run `docker compose ps worker` and `docker compose logs worker`.

**Fix.** Start a worker (`make worker`, or the `worker` service) on the same `ARIA_DATABASE_URL` as the API. Or switch a single-process deployment to `inprocess`. After a restart in `inprocess` mode, the API picks up unfinished runs itself (`worker.recovered`).

### A provider's circuit is open, or LLM steps keep failing

**Likely cause.**

- A wrong or expired key.
- A model ID the provider does not serve.
- A provider that is overloaded. A timeout opens its circuit at once, for 5 minutes.
- A network or proxy block.

**Check.**

- `GET /api/v1/providers` shows `breaker: open` and the `last_error`.
- Reports are written by the template, and `/readyz` reports `degraded`.
- Logs show `llm.provider_error`.
- Run `uv run aria providers check <name>`.

**Fix.** Correct the key or the model variable and restart. A breaker that opened after three failures in a row lets one trial request through after 30 seconds; meanwhile the chain falls back to the next provider. Breakers live in memory, so a restart closes them.

### Runs fall back to rules only

**Likely cause.** The run spent one of its budgets: tokens, cost, LLM calls, elapsed time, tool calls or steps. A slow provider usually spends the time budget first. This is by design: a run never fails for lack of budget.

**Check.** `GET /api/v1/runs/{run_id}` shows `budget.exhausted` and the run's `notes`.

**Fix.** Raise the limit in `budgets` in `config/aria.yaml`, or route to a faster model or a self-hosted NIM.

### Webhooks are rejected

**Likely cause, by status.**

| Status | Cause |
|---|---|
| 401 | The sender sends no key, or a wrong one |
| 422 | The payload has no alerts, or ARIA's own alert format failed validation |
| 429 | That key name has spent its rate limit |
| 503 | The API is still starting |

**Check.** The response body's `detail`, and the API's access log.

**Fix.**

- **Alertmanager.** Send the key from the webhook receiver:

  ```yaml
  receivers:
    - name: aria
      webhook_configs:
        - url: https://<api host>/api/v1/alerts/alertmanager
          http_config:
            authorization:
              type: Bearer
              credentials_file: /etc/alertmanager/aria-key
  ```

- **Grafana.** Give the webhook contact point an `Authorization` header of `Bearer <key>`, and point it at `/api/v1/alerts/grafana`.
- **Rate limits.** Give each alert source its own key name, so it gets its own bucket, or raise `ARIA_RATE_LIMIT_PER_MINUTE`.

### An approved message was not delivered

**Symptom.** The run page's **Messages** card says "Not delivered", and the logs show
`notify.failed`. A message ARIA skipped says why, for example that its channel's webhook URL is
not set.

**Cause.** The receiver was down or refused the message. ARIA tries twice (once more after a 5xx
or a network error), then records the failure; it never retries on its own.

**Fix.** Once the receiver is back, choose **Send again** on the run page, or call
`POST /api/v1/runs/{run_id}/actions/{action_id}/resend`. Only a message a reviewer approved and
whose delivery failed can be sent again, and only once at a time: a message that went out is never
repeated (409). The run's events record who resent it. For a skipped message, set its channel's
variable ([Configuration](#configuration)); a skipped message is not resent.

A message whose process stopped while sending it stays marked as being sent. Once the run has
ended, the card says "Delivery not confirmed" and offers **Send again** too. It may already have
gone out: the resend carries the same idempotency key, so a receiver that keeps those drops the
repeat. Check the receiver first if it does not.

### The scan opens no runs

**Likely cause.**

- `ARIA_SCAN_INTERVAL_S` is 0, or `ARIA_SCAN_SOURCES` is empty; the scan needs both.
- The file is not visible where runs execute.
- Only old lines are in the file: the scan starts at its end.
- The burst score stays below `triggers.scan_min_burst_score`.
- `system` names the wrong log format.
- A scan run for that system is still open, or started within the grouping window.

**Check.** Logs show `scan.started`, `scan.covered` (a run already covers that system), `scan.failed` and `scan.run_opened`. Runs the scan opens have `trigger: scan`.

**Fix.** Set both variables in the process that executes runs, and mount the file there. Append new lines to test it.

### The safety check flags everything

**Likely cause.** The check fails closed. It flags everything when:

- no safety provider is available, because `NVIDIA_API_KEY` is missing;
- the safety model ID is not served;
- the safety model errors or times out;
- the run's budget is spent;
- the model answers in a form ARIA cannot read.

**Check.** Run notes read "the LLM report was flagged by the content-safety check (…)" or "comms draft for … dropped". The text in brackets gives the reason, for example "no safety model is configured", "the safety model did not answer" or "unreadable verdict". Run `uv run aria providers models nim` to see whether the model is listed.

**Fix.** Set the key and a served model ID, or set `guardrails.safety_model: false`.

### `/api/v1/tickets/assess` answers 503

**Likely cause.** No ticket model was found at start: `models/severity_ticket.json` is missing, or a mounted models directory hides the copy in the image. The log shows `services.ticket_models_missing` at start.

**Fix.** Train it from the UCI incident log (the download falls back to checksum-pinned mirrors when the UCI host is blocked), then restart the API, which loads the ticket model at start. In containers, mount the new file into the models directory or rebuild the image.

```bash
uv run aria data download --source uci-incidents
```

```bash
uv run aria train tickets
```

### The web app cannot reach the API

**Likely cause.**

- `ARIA_API_URL` is wrong. Its default is `http://127.0.0.1:8000`; compose uses `http://api:8000`, and Azure uses the API's HTTPS address.
- The API is down.
- A proxy intercepts local traffic.

**Check.**

- The console says the API is not reachable, and proxied calls answer 502.
- `GET /api/session` returns `"reachable": false`.
- The web app logs "ARIA API unreachable" with the target origin.
- From the web container, run `docker compose exec web node -e "fetch('http://api:8000/healthz').then((r) => console.log(r.status))"`.

**Fix.** Set `ARIA_API_URL` and restart the web app. If the API answers 401, the stored key no longer works: sign in again.

### Migrations are out of date

**Likely cause.** The code expects tables or columns that the database lacks, because `aria db upgrade` did not run.

**Check.** Requests fail with errors about missing tables or columns, but `/readyz` still reports the database as up: it only runs `SELECT 1`. Compare `uv run aria db current` with the newest file in [`src/aria/db/migrations/versions`](../src/aria/db/migrations/versions).

**Fix.** Run `uv run aria db upgrade`; in compose, `docker compose exec api aria db upgrade`. On Azure, restart the API revision; it migrates as it starts.

### The disk is full

**Likely cause.** Several things grow without limit:

- the SQLite database: runs, checkpoints and events are kept until deleted, and each run stores its raw request;
- Phoenix trace data;
- the NIM model cache;
- Docker images and build cache.

**Check.** Run `docker system df` and `docker compose exec api df -h /var/lib/aria`.

**Fix.**

1. Delete runs you no longer need with `DELETE /api/v1/runs/{run_id}`, then compact the database: `docker compose exec api python -c "import sqlite3; sqlite3.connect('/var/lib/aria/aria.db').execute('VACUUM')"`.
2. Prune the build cache with `docker builder prune`.
3. For production volumes, use Azure SQL.

## Alerts and SLOs (suggestions)

Nothing in this section ships with ARIA. These are starting points to adapt to your own paging policy. The rules assume the scrape job above is named `aria`:

```yaml
groups:
  - name: aria
    rules:
      - alert: AriaApiDown
        expr: up{job="aria"} == 0
        for: 2m
      - alert: AriaRunsWaitingForAWorker
        expr: aria_runs{status="queued"} > 0
        for: 10m
      - alert: AriaReviewBacklog
        expr: aria_runs{status="awaiting_review"} > 10
        for: 30m
      - alert: AriaRunsFailing
        expr: delta(aria_runs{status="failed"}[1h]) > 0
```

Watch these in logs or by polling, since no metric covers them:

- an open provider circuit (`/api/v1/providers`, `llm.provider_error`);
- failed deliveries (`notify.failed`);
- recalibration errors (`severity.recalibration_failed`);
- an API running without keys (`api.open`);
- a stale worker heartbeat (`aria worker-health`).

Suggested service levels:

| Objective | Suggested target | How to measure |
|---|---|---|
| API availability | 99.5% of `/healthz` probes succeed over 30 days | Probe or scrape `up` |
| Queue wait | No run waits in `queued` for more than 2 minutes | `aria_runs{status="queued"}` |
| Time to review | 95% of runs are ready for review within 5 minutes of the alert, with a live provider | `aria_time_to_review_seconds` in `inprocess` mode. In `external` mode, use the run records' timestamps, because the histogram sees only the API process. |
| Delivery | Every approved message is sent or marked failed within a minute of approval | `notify.sent` and `notify.failed` |
