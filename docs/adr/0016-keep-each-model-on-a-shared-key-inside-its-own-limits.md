# 0016. Keep each model on a shared key inside its own limits

## Status

Accepted. Extends [0005](0005-route-model-calls-through-provider-chains.md).

## Context

The public demo shares one Gemini API key among every visitor. Google limits each project per
model, in requests a minute, input tokens a minute and requests a day, and starts the daily count
again at midnight Pacific time. A model that hits a limit refuses with HTTP 429 until the window
passes, and a busy one answers 503. Before this decision ARIA called its first model until it was
refused, then fell to the next: visitors met refusals and slow fallbacks, and one long triage
could use up the day's requests halfway through.

Spreading load over several accounts or keys to multiply the free limits is against the
providers' terms, so the limits of one key are a fixed budget to spend well.

## Decision

**A pool of models on the one key.** Each Gemini model is a provider of its own in
[`config/aria.yaml`](../../config/aria.yaml), with its own limits and the role it serves best: the
strongest model leads the investigator and the report, and lighter models with larger daily
limits take the critic, message drafts and Ask ARIA. The defaults are cautious placeholders; the
owner copies the real numbers from AI Studio into environment variables.

**A quota ledger** ([`quota.py`](../../src/aria/llm/quota.py)) paces every model:

- a one-minute window for requests and tokens, so no minute ever holds more than the limit;
- a count of requests per day that starts again at midnight in the configured time zone;
- a safety margin, since other apps may share the project;
- counts and holds saved to a small file, replaced atomically, so a restart remembers today.

**Admission before every call.** The router asks the ledger first and gives the call to the best
model with room, so ARIA stops before a limit instead of at a 429.

**Reservations for whole runs.** A model-written triage sets aside the day's requests it needs
before it starts. When no model has room, the run is written offline, with a plain message saying
when the shared model is back.

**Refusals are classified** ([`ratelimit.py`](../../src/aria/llm/ratelimit.py)) as per-minute,
per-day or a spending cap. Per-day and spending-cap refusals hold that model until its reset.

**One retry layer, a response cache and a capacity view.** A transport error is retried in one
place only. Identical deterministic requests are answered from an in-memory cache, never for a
visitor's own key. `GET /api/v1/llm/capacity` shows each model's remaining room, with no secrets.

**Visitors' own keys bypass the pool**: they never spend the shared budget and never read the
cache.

## Alternatives considered

- **Rotate several free accounts.** Against the providers' terms.
- **Queue every call until a model has room.** Visitors would wait minutes behind each other; an
  offline report now, with a time the model is back, serves them better.
- **A paid tier only.** It lifts the limits, but costs money on a public demo. Billing with a
  monthly spending cap stays the owner's choice, and the ledger treats a reached cap like a daily
  limit.

## Consequences

- Under normal load no call is refused for a limit; the demo degrades to offline reports, never to
  errors.
- Each process counts only its own requests: run one process per key, or give each process its
  share of the limits.
- The limits in config must match the key's real limits. Placeholders that are too high let 429s
  through, which the ledger then honours; placeholders that are too low waste capacity.
