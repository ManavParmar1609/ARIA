# 0005. Route model calls by role through config-defined provider chains

## Status

Accepted.

## Context

ARIA must run on NVIDIA NIM (hosted or self-hosted), Google Gemini, Azure OpenAI or any
OpenAI-compatible server, and fully offline for tests, evals and the demo. Model IDs change
quickly, and a hosted model can be slow or down for hours. A run must never fail just because a
model is unavailable or a budget is spent.

## Decision

- **Config only.** [`aria.yaml`](../../config/aria.yaml) lists providers by kind: `nvidia_nim`,
  `azure_openai`, `openai_compatible`, `fake`, and `local` for offline embeddings. Endpoints and
  model IDs come from environment variables with defaults. A provider names the environment
  variable that holds its key, never the key, and one without an endpoint or key is disabled and
  skipped. Each entry records whether its model IDs were `verified` with live calls.
- **One adapter.** [`OpenAICompatibleProvider`](../../src/aria/llm/openai_compat.py) serves every
  real provider. Differences are confined to URL construction, authentication (an API key, or
  Entra ID for Azure) and how JSON output is requested; when a provider rejects a mode it steps
  down from `json_schema` to `guided_json`, `json_object` and plain prompting.
- **A chain per role.** [`LLMRouter`](../../src/aria/llm/router.py) gives each role
  (`adjudicator`, `investigator`, `reporter`, `critic`, `comms`, `ask`) an ordered chain: a
  self-hosted NIM, Gemini and a lighter Gemini model, hosted NIM and a second NIM model, Azure
  OpenAI, an OpenAI-compatible endpoint and the fake provider. A provider may name more than one
  environment variable for its key; the first one set is used. Embeddings, reranking and the
  safety model have their own chains. A run can put one provider first for every role.
- **Validate before falling back.** Structured output is checked against its Pydantic schema and a
  caller's own check (for example, cited evidence must exist). The model gets one repair attempt
  with the errors, then the router tries the next provider. When the chain is exhausted, the
  caller takes its deterministic path.
- **Circuit breakers.** A provider's breaker opens for 30 seconds after three consecutive
  failures; a timeout opens it at once for five minutes; and a refusal that says how long to wait
  (`Retry-After`, or Gemini's retry info on a rate limit or quota) opens it at once for that long,
  up to an hour, so calls stop spending the provider's limit on refusals. Providers that stream
  every request fail over when they send nothing for `stall_timeout_s`.
- **Limits counted before each call.** A provider may declare its rate limits (`limits`: requests
  a minute, tokens a minute, requests a day). The [quota ledger](../../src/aria/llm/quota.py)
  counts every request against them, less a safety margin, before the request goes, and the router
  skips a provider with no room. A refusal for a limit is read for what it names
  ([`ratelimit.py`](../../src/aria/llm/ratelimit.py)): a per-minute limit rests the provider for
  its delay; a daily quota, a spending cap or an empty account rests it until the daily reset. A
  model-written run reserves its calls before it starts, and runs offline when they do not fit.
- **One retry layer.** A client sends each request once. When it fails, the next provider in the
  chain takes the call; that fallback is the only retry a model call gets, so one failure never
  multiplies into several requests against the same limit. The graph's node retry policy retries
  database and tool-server errors, never a model call.
- **Budgets.** [`BudgetGuard`](../../src/aria/llm/budget.py) checks tokens, cost, LLM calls, tool
  calls, steps and wall-clock time before each call, against limits in config that a run can
  only lower, for tokens and cost. A spent budget raises `BudgetExceededError`; the agent falls
  back to its deterministic path, so the run degrades to rules and templates instead of failing.
- **The fake provider** ([`fake.py`](../../src/aria/llm/fake.py)) answers deterministically from
  the same context a real model receives, so offline runs exercise the real prompt contract,
  validation and repair paths. Its output always carries provider `fake`. It is refused when
  `ARIA_ENV=prod`, and the adjudicator's chain leaves it out on purpose: without a real model, the
  conservative severity policy decides.

## Alternatives considered

- **A framework's chat-model abstraction.** It would sit between ARIA and the HTTP calls it needs
  to control: stall detection on streams, structured-output step-down and per-call budget
  accounting.
- **One provider per deployment.** Simpler, but one slow model would stall every run.

## Consequences

- Switching provider is a configuration change. The adapter is contract-tested against mocked
  HTTP for Gemini, NIM, Azure OpenAI and OpenAI-compatible endpoints.
- Fallback hides provider trouble from the run, not from operators: `aria providers check` checks
  keys, catalogs and model IDs, `/api/v1/providers` reports breaker state, and every LLM call is a
  run event.
- The cost limit binds only for providers with prices configured. None of the shipped provider
  entries sets a price, so today the limits that bind are tokens, calls, steps and time.
