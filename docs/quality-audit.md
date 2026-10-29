# Quality audit

Before showing ARIA to people who might adopt it, it was audited end to end: how it looks, how it
moves, whether every flow works and is worth using, how it handles hostile and unusual input, whether
its evidence is honest, and whether it is ready to run in production. This page records what each
audit checked, what it fixed, what it left and why, and how to run the checks again.

Every number ARIA publishes comes from `make eval` ([evaluation.md](evaluation.md)); this page
quotes none.

## How the audit worked

- **Independent sweeps.** Each track was a separate read-only review that reproduced every finding
  against its own instances of the API and the console: offline, with provider keys blank, each on
  a fresh database, so no finding depended on a paid call or on another sweep's state.
- **Verified before fixed.** Each finding was reproduced again before it was fixed. Findings that did
  not hold up, or whose fix would cost more than it prevents, are listed under
  [What was left](#what-was-left) with the reason.
- **Fixed at the root, with a test.** Every confirmed bug got the smallest sound fix and a regression
  test that fails without it. Changes that move a published number were followed by `make eval`,
  run on a clean tree so the results name the commit they came from.

## What each audit checked and fixed

### Edge cases and severity safety

Checked: empty, tiny, huge, unicode, duplicate and malformed input over REST, webhooks, A2A, AG-UI
and the CLI; concurrent runs; resume, fork and time travel; hostile alert labels.

Fixed (287d817):

- **A single log line could be rated SEV1 automatically.** The calibrated model extrapolated on
  windows far smaller than any it learned from: one line, a few lines, or an alert with no logs. Now
  a window with a feature more than six training standard deviations from the training mean skips
  the model. The rules set the choices, the evidence says why, and a person always confirms. No
  window in the training or held-out scenarios is that far out, so the published scenario numbers
  do not move. Real HDFS traffic is far faster than the scenarios, so on real logs the model now
  steps aside and the rules decide, with review ([model card](model-card.md), decision step 4).
- **Considered and not adopted:** also refusing to auto-decide when the model and the rules are two
  or more levels apart. On the held-out scenarios the model was right in nearly every such case
  (mostly the rules over-calling), so the rule would have added reviews without catching errors.
- **500s became clear errors:** malformed Alertmanager payloads, fork options and event cursors now
  answer 422, a `Last-Event-ID` that is not plain digits is ignored, a system name with a dot is
  refused before it can break the memory namespace, and an over-long service name is refused before
  it can fail the run's messages.
- **Reviewer edits that failed the run** (a summary line too long for a claim) or published blank
  claims are refused with 422, and the run keeps waiting for review.

### Security and untrusted text

Checked: authentication, rate limits, secrets, headers, CORS, redaction, the injection guard, and
every path untrusted text takes to a model, a message or storage.

Fixed (287d817, 5d74564):

- **Secret formats that slipped past redaction:** settings named like secrets (`DB_PASSWORD=`,
  JSON and escaped JSON keys, `AccountKey=`, `--password`, a SAS `sig=`), Basic credentials,
  private keys printed over several lines (shards never split one), and Google, Stripe, SendGrid,
  GitLab, fine-grained GitHub and Slack webhook tokens. The scan stays linear on hostile input.
- **Alert names and labels reached trusted prompt facts, titles and messages raw.** Secrets are now
  redacted as an alert arrives, before anything stores it. When a run starts, every alert field,
  the title, the service and the environment are cleaned once: addresses get the run's pseudonyms
  (matching its log lines), and a value that reads like an instruction is withheld whole.
- **Any client could attach a real incident's expert labels to its own logs**; only the replay
  endpoint can now.
- **Production hardening:** no API docs in production; a keyless readiness check says only whether
  ARIA is ready; HSTS over HTTPS; on Azure the API trusts only the private addresses its ingress
  forwards from (trusting every address would let a caller write its own); the rate limiter forgets
  callers once their bucket has refilled, so many addresses cannot grow it without bound; each Ask
  ARIA question has its own LLM budget; AG-UI and A2A runs share the worker's concurrency slots.

### Functional and usefulness

Checked: first visit, sample triage, live runs, review and publish, Ask ARIA, memory, runbooks,
evaluation, settings, palette and shortcuts, the API, MCP, webhooks and the CLI.

Fixed (287d817, a9f2d9e):

- **A reviewer's severity or title change did not reach the messages sent** or the report heading.
  Approved drafts are now rewritten from the reviewed report, and the heading leads with the final
  severity.
- **Every message linked to a URL that answered 404.** Messages link to the run in the console
  (`ARIA_CONSOLE_URL`), and to the API's run otherwise. Messages say "our service" rather than the
  name of the generic log format.
- **Unrelated alerts merged into one run, and a deleted run swallowed its group's later alerts.**
  Alerts that share no labels never group, and a deleted run's group is closed.
- **Reviewing a queued run answered 404,** and the expert check of a queued replay said it was not a
  replay. They now answer 409 and "not ready".
- **Reconnecting to a finished run recorded its end again** and inflated the metrics; the end is
  recorded once.
- **The external worker died mid-run on SIGTERM,** leaving runs claimed until the claim expired. It
  now stops claiming, finishes the runs in hand and exits.
- **Pinning a citation jumped the page** and left the evidence below the fold (a9f2d9e).

### Data and evidence

Checked: splits, leakage, baselines, confidence intervals, and every claim made about real data.

Fixed (23d7f36, 409db39, and the results regenerated after 03af0b8):

- The real-log evaluation is reported as it is: exact (Clopper-Pearson) intervals, recall over every
  labelled failure beside recall over the failures a window could judge, the share judged, four
  standard unsupervised detectors on the same blocks, a window-length sweep, and a replay of the log
  from its start. A claim of beating the detectors appears only when the measured F1 supports it.
- The docs call the scenario results semi-synthetic everywhere, and say which limits are real: one
  real log from one system, no untouched test set for the scenario suite, rules and features that
  mirror the generator.
- The explainer video's measured scene adds the real-log result, read from the generated results.

### Aesthetic and copy

Checked: every page and state at 320 to 1920 px in both themes, for type scale, spacing, alignment,
hierarchy, clutter and copy.

Fixed (a9f2d9e, 03af0b8): the run page's two-column layout now starts only when both columns fit;
the incidents table, landing navigation and example run no longer crush or wrap at laptop widths;
tabs keep their focus ring; one severity per row in memory and the palette; the overview no longer
lists waiting runs twice and says what its stats count; "Needs review" is ink rather than done-green;
one name, "offline mode", for running without an LLM; severity copy in plain words; chart labels no
longer overlap; hyphens in code and IDs are no longer spaced out; the sidebar keeps its focus rings
and fits laptop heights; sample names keep their capitals; guide rows align; evaluation bars keep
their width on phones; browser tabs name the incident or runbook.

### Animation

Checked: each of the six chosen animations for distraction, legibility, layout shift, reduced motion
and cost on phones.

Fixed (5371b89, 0e5623c): nothing moves for more than a few seconds (WCAG 2.2.2): the hero's drift
became a single entrance and the waiting dot pulses three times, then rests. The severity stamp
scales and turns but never fades, so its label keeps its contrast in every frame, and an axe check
now runs on frozen frames of the run page while the stamp lands. Below 1024 px the hero arrives as
one composited piece, which keeps the main thread free on phones. Under reduced motion every
animation shows its final state.

### Onboarding and the video

Checked: a fresh clone through the README's quickstart, and every frame of the explainer.

Fixed (c5343d9, b8d33e0): a fresh install no longer warns about skipped build scripts (they are
skipped on purpose and now listed as such), and each scene's title waits for the crossfade instead
of overlapping the previous title.

## What was left

These are recorded rather than fixed, because each needs a design change, infrastructure or an
owner's decision. The [threat model](threat-model.md) lists the security residuals in detail.

- **Several API replicas.** A run can be resumed or executed twice when two replicas race, an alert
  storm delivered concurrently can open several runs, and a delete racing a review can leave
  checkpoints behind. Fixing these needs database-level claims or locks on runs and alert groups.
- **External-mode AG-UI and A2A runs** that were running when the API restarted stay "running", and
  cannot be deleted. The worker would need to reclaim them, or these transports would need to queue.
- **Forks** from some checkpoints of a published run fail or start nowhere, and a fork at review has
  no stored report until it is approved.
- **Streams and slow clients.** Event streams have no per-caller cap or maximum lifetime, a stream on
  a deleted run keeps sending pings, and slow-header connections are held open. Front the API with a
  proxy that enforces these limits.
- **Stored raw input.** The run record and its first checkpoint keep the request as sent, and nothing
  purges old runs. Store only the redacted batch, or encrypt the request, and add a retention job.
- **The model's training range.** Windows much busier than the scenarios it learned from (real HDFS
  traffic, for example) are rated by the rules and confirmed by a person until the model is
  retrained on the deployment's own windows.
- **Smaller issues:** CLI errors print tracebacks; MCP hides why an ID is unknown; the injection
  detector misses some spaced-out, homoglyph and role-play variants; Markdown exports pass raw HTML
  through (the console does not render it); the console's benign Cocoa sample is rated SEV2; the web
  CSP needs `'unsafe-inline'` for prerendered pages; MCP log search scans without an index; images
  are pinned by tag, not digest.
- **Smaller UI items:** what "incident" means in two places, raw identifiers in a few labels, chart
  text that is small on phones, the Ask page's suggestion chips, data-table row headers, run progress
  chips and run rows on phones, landing log lines on phones, vague error states, the landing page
  repeating itself, template counts, and a phone tap on a citation that jumps far down the page.
- **For the owner:** rotate the NVIDIA key in the git-ignored `.env` (it notes it was shared in a
  chat); run the live LLM evaluation (`aria eval run --suite pipeline --llm`, which spends provider
  credits); and, with access to Zenodo, add more real labelled logs from pinned sources.

## How to run the checks again

```bash
make lint
```

```bash
make test
```

```bash
make eval-smoke
```

```bash
make eval
```

```bash
make web-check
```

```bash
make web-e2e
```

```bash
make openapi
```

```bash
make audit
```

`make eval` rewrites every published number and the blocks quoted in the README and the model card;
commit what it rewrote. `make web-e2e` includes axe in both themes, the 320 px reflow check and the
frozen-frame check of the severity stamp. CI runs all of these on every push, with the Lighthouse gate and the
video render.
