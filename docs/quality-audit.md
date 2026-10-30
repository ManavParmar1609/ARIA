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
  The run page says so too: when the model stepped aside, its severity chart calls the bars rule
  scores and the bracket the levels the rules leave open, never a calibrated confidence.
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
- **Markdown exports passed raw HTML, links and chat mentions from logs through** to whatever they
  were pasted into; that text is now escaped and stays inert.
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
- **Forking failed from five of a published run's twelve checkpoints** (in front of parse, merge,
  investigation, the report and publishing): LangGraph drops a pending route when a fork updates
  the state there. A fork from any checkpoint now reaches review: in front of such a step it
  starts from the nearest earlier step that can take the update, and in front of publishing it
  goes back to review, so a fork never publishes on its parent's approval. A fork taken after the
  report step stores its own report and drafts at once, so they can be downloaded before
  approval.
- **Rough edges for people using it** (83d8936 and after): the CLI answers a missing or empty log
  file, an unknown scenario, suite, provider or source, and a database that is not set up with a
  sentence saying what to do; MCP tells a caller why an incident or runbook ID is unknown; an event
  stream ends when its run is deleted.

### Data and evidence

Checked: splits, leakage, baselines, confidence intervals, and every claim made about real data.

Fixed (23d7f36, 409db39, and the results regenerated after 03af0b8):

- The real-log evaluation is reported as it is: exact (Clopper-Pearson) intervals, recall over every
  labelled failure beside recall over the failures a window could judge, the share judged, four
  standard unsupervised detectors on the same blocks, a window-length sweep, and a replay of the log
  from its start. A claim of beating the detectors appears only when the measured F1 supports it.
- The docs call the scenario results semi-synthetic everywhere, and say which limits are real: at
  the time, one real log from one system (the final audit below adds five more real datasets), no
  untouched test set for the scenario suite, rules and features that mirror the generator.
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

Then: the run page no longer repeats its title and ID; error messages name what failed and what
to do (never a bare "Internal Server Error"), settings shows one error instead of three, and a run
or runbook that fails to load keeps a way back; runbooks say "Any system", keep "mod_jk" whole and
tag only the riskier steps; incident memory shows 20 incidents at a time, tags the rarer kind and
drops "seen 1 time"; template rows and the guardrails line say what they count in words. On the
landing page, the story cards stack below 1024 px, the standards links line up, "How it works"
has no empty bands under reduced motion, the risk chart is centred, the median time appears once,
and the closing promises that repeated the hero are gone.

Last: on a phone, a tapped citation offers "Back to the claim", run rows keep more of their title,
progress chips show whole step names, and the landing page's log lines wrap instead of stopping
after a few words; on wide screens the chips wrap evenly. Identifiers became words: step names on
the evaluation page, checkpoint labels, provider chains grouped by role, evidence data, failure
modes in titles ("DNS resolution failures", not "Dns resolution"), and "1 node" and "1 shard".
Table row headers read like their rows, the lifecycle check's two settings have plain names, and
the Ask page's suggestions are chips in their own row. Labels set below the 13 px floor of the
type scale (small severity tags, risk tags, the rule trace, the quarantine flag) were raised to it,
and the one bold figure uses the medium weight like everything else. An offline run says "offline mode: no LLM"
rather than counting the deterministic provider's calls as model calls (the overview stops
counting its tokens too), and message drafts name the system as people write it ("HDFS").

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
of overlapping the previous title. Later, `make dev` applies the database migrations before it
starts, `aria serve` on a database that is not set up says what to run instead of stopping with a
traceback (unless the deployment migrates on start, as on Azure), and SQLite's write-ahead files
are ignored by git. The recorded run behind the landing page and the video was recorded again, so
its message drafts name the system properly, and the README's run and replay screenshots were
retaken to show the console as it is now.

## The final audit

A last pass ran four independent reviews of the whole branch: security and operations, functional
behaviour and edge cases, docs and developer experience, and presentation and accessibility in a
real browser at every width from 320 to 1440 px, in both themes. Each ran offline on its own API and
database, and each finding was reproduced before it was fixed.

### Security and operations

- **One process drives a run at a time** (0865806). Every drive claims its run and renews the
  claim; a review applied long after the pause can no longer publish twice, a worker no longer takes
  over a run another process holds, and each approved message is claimed once before it is sent.
- **Untrusted text stays fenced** (baa139d). Report drafts, critic claims, hypotheses and queries
  that quote logs reach a model only inside `untrusted_data` fences. Titles, alert names and ticket
  fields are cleaned when a run is created or forked, so no checkpoint or run list holds them raw.
- **Bounded and off the event loop** (e62e14e, baa139d). The console counts request bytes before it
  reads a body; the e-mail redactor runs in linear time; MCP database tools run off the event loop
  and log search needs a run or a system; the A2A task store keeps only its newest tasks.
- **Access and operations** (0865806, baa139d). A proxy prefix no longer opens protected paths;
  every protected request leaves an access log line; production refuses short API keys; readiness
  probes spend the rate limit on a wrong key; the worker answers HTTP liveness probes; the image
  keeps code root-owned; incident memory in each process follows publishes and deletes elsewhere.

### Functional behaviour and edge cases

- **Reviews say what they did** (0865806, 52bea0e). Edits sent with an approve or reject are refused
  instead of recorded and dropped; a misspelt field is refused; a reviewer's new title reaches the run
  list; a review or delete that arrives as the run pauses waits for it instead of failing.
- **Messages** (0865806, 997c040). Alert labels never reach a customer draft verbatim; a link or a
  phone number in a draft is flagged. An approved message whose delivery failed can be sent again
  from the run page, once, and nothing else can; the approval toast counts what was delivered.
- **Clear answers at the edges** (baa139d, 52bea0e). A ticket with a severe model priority sets a
  floor; an unknown window is a 422; Ask about a queued run is a 409; AG-UI refuses new logs on a
  finished thread and names what is wrong with a request; A2A, AG-UI, MCP and the CLI report problems
  in one readable line; MCP resources and prompts name an unknown runbook or incident.
- **Retrieval** (52bea0e). A similar incident from another system grades lower than the same match
  on the run's own system, so an analogue no longer outranks the system's own history.

### Docs and developer experience

- `aria train severity` no longer replaces the committed model with one fit on the test fixtures;
  `make dev` takes `API_PORT` and `WEB_PORT`; `aria providers check NAME` fails for an unconfigured
  provider; the terminal report is rendered, not HTML-escaped (52bea0e).
- Offline runs no longer claim a model wrote the report, in the export, the run page or the agent
  story (baa139d, and the presentation fixes below).
- ADRs 0003, 0004, 0005 and 0011, the threat model, the data card, the runbook and AGENTS.md match
  the code again (baa139d), and no doc refers to the machine the project was built on (52bea0e).

### Presentation and accessibility

- **Honest numbers.** The BlueGene/L card and the README's generated sentence set ARIA beside its
  own rules and the highest log level, not the weakest baseline; the Hadoop card gives the ERROR rule's
  false alarms; the real-log section says its settings were chosen with the labels in view; the
  injection headline sits beside the detector's result on public attacks; coverage is stated as the
  target it is, not a guarantee; the live-model note gives the reason the data supports.
- **Accessibility.** The phone header's link is named for what it shows (WCAG 2.5.3), with a 375 px
  axe pass in the end-to-end suite; Markdown task boxes no longer render as unlabelled checkboxes;
  skip links keep their padding; focus and anchors land clear of the floating nav.
- **Layout and copy.** The step strip, chart ticks, dataset cards and bar labels fit their width; the
  green road ends on round caps; a tapped citation on a phone shows its evidence beside the claim;
  static console pages stay readable while the API is down, and links to a section scroll to it;
  printed pages show every number; jargon on the landing cards is explained.
- **Exports.** Emphasis and code marks in log text stay literal, so a template's `<*>` no longer
  turns the text after it italic.

### The code review of these fixes

A code review of the audit's own commits found ten problems, and fixing them turned up one more.
Ten are fixed, each with a regression test (f5b6e83); one is left on purpose.

- **Claims.** An A2A request cancelled while it waited for a slot kept its run's claim, renewed for
  good, so no process could ever run it: the claim is now let go. Each runner claims under a name
  of its own, so a restarted container never takes a dead predecessor's claims for its own. A
  claim goes stale after 5 minutes instead of 10, so a crashed process's runs resume sooner, and a
  worker with every slot busy leaves abandoned runs to the others instead of claiming runs it
  cannot start.
- **Messages.** A message whose process stopped while sending it stayed "Sending" for good. Once
  its run has ended, the run page now says the delivery was not confirmed and offers **Send
  again**, which holds the run as a drive does and sends with the same idempotency key. A bare
  domain such as `status-help.com` now counts as a link, and a service label that is a domain or a
  host name gives way to the system's name, so a message never fails its own check and goes
  missing.
- **Pseudonyms.** Without `ARIA_PSEUDONYM_KEY`, each process made its own key, so the API, which
  cleans alerts, and a worker, which parses the logs, gave one host two pseudonyms. They now share
  one random key kept in the database.
- **Memory and redaction.** Memory in each process reloads when another process edits an incident,
  not only when one is added or removed. An e-mail address whose local part is longer than 64
  characters is redacted too.
- **Reviews.** Saving an edit sent the whole form back, so changing only the title re-cited every
  summary line to the review and dropped the evidence it cited. The panel now sends only what
  changed, and a summary line the reviewer kept keeps its evidence.
- **Tests.** While these fixes were checked, an accessibility scan caught a toast halfway through
  fading out, which reads as low-contrast text. The scans now read the page with motion reduced,
  so they measure what a person sees once it is still.
- **Left on purpose:** a worker driving a run renews its claim twice a minute, once for the drive
  and once with the other runs it holds. That is one extra update a minute, and it changes nothing.

A second review, of those fixes, found ten more problems. Nine are fixed, each with a regression
test (5f5d310); one is left.

- **Claims.** A run a worker recovered with nothing left to drive (it had reached review, or
  ended) kept its claim for good, so a review applied from another process was refused: the claim
  is now let go. Giving a claim up waits a moment for a resend or a delete that holds the run, a
  streamed run in a slot counts as busy, and a runner's name fits the claim column however long
  the host name is.
- **Memory.** Writing an embedding back no longer counts as an edit, so processes on different
  embedding models no longer reload, and re-embed, each other's rows every minute. Changes are
  found from every incident's ID and update time together, so an edit made by a process with a
  slow clock is not missed.
- **Messages and reviews.** An e-mail address is redacted whatever the length of its local part,
  still in linear time. Publishing an edit that changes nothing says so in the dialog instead of
  sending a request the server refuses. The resendable states and the store's namespace separator
  are each defined once.
- **Left:** resending a message still marked as being sent relies on the run's claim. The process
  sending a message renews that claim every minute and each send has a timeout, so a resend can
  overlap a send only if the sending process freezes for five minutes; the resend's idempotency
  key covers that case for receivers that honour it.

### Alert storms on several replicas

The audit had left this open, and it is now fixed (cb5e51c, then 23a0a90). A burst of deliveries
for one new alert group opened several runs, even on one replica: each request found the group
still without a run and opened its own, and two replicas could each open a group. The database
now keeps one open group per alert key (a unique index; the migration closes any duplicates a
database already holds), and a request that loses the race joins the winner's group. A group's
run takes an ID that follows from the group, and every request tries the same IDs in the same
order, so racing requests end up on the same run, even when another run already holds the first
ID; a run is attached to a group only if the group has none. A run's start is recorded only by
the process that wins it. A first version derived each group's ID from the group before it; a
review of it showed that clock skew between replicas could defeat that, so the database
enforces the rule instead. Left on purpose: a run recovered after its process stopped before the
first checkpoint records a second start, because it did start again.

## The second audit

After the redesign as a greenhouse on cream paper and the addition of Google Gemini, a second round
ran five sweeps the same way: aesthetics and layout (every route at phone to wide desktop widths,
both themes, every state), every functional flow against its own instances, gaps and weak spots
from a fresh clone, motion and performance, and leftovers and stale docs. The same round published
the first live evaluation on Gemini and restyled the explainer video.

### Functional

- **A wrong cause, stated with confidence.** For a web app's NullPointerException, the offline
  investigator offered a supercomputer's past kernel panic as the cause, and every generic check
  (example lines, a busy timeline) seemed to bear it out. A past incident from another system with
  no component in common is no longer tested as a cause, named in a title or written to memory
  (0e6c0da).
- **ARIA's own report failed its own checks.** A timeline line cut inside "50010" left "500", which
  no evidence holds, and redacting a quote of already redacted evidence flagged `[REDACTED]` as a
  credential. Text is now cut between words, and redaction finds nothing new in redacted text
  (0e6c0da).
- **Simultaneous reviews.** Approve and reject sent at once all answered "published". The run is
  now re-checked under its claim, so only the first review counts and the rest get 409 (0e6c0da).
- **Smaller fixes.** The approval switch follows the server's rule (a6589b4); chat samples are
  recorded as semi-synthetic; memory keeps plain titles and Ask ARIA says a learned incident's
  steps were approved, not that they fixed it; a run naming an unknown or unconfigured provider
  gets 422; `aria providers models` explains a provider that is not set up; titles on unnamed
  systems name the failing component (0e6c0da). Blank-only logs are refused, the MCP prompt takes
  only a plain system name, the A2A card names the address ARIA serves on, approved deliveries
  with no receiver keep their approver, and a system name fits the database column (ec76e30).
  A refused request is answered in plain words without echoing the body back.

### Gaps and weak spots

- **Untested safety paths, now tested:** publishing retries after a message went out and still
  sends it once; card numbers that need the Luhn check; severity properties (always inside the
  prediction set, never under the floor) and the contract's backstops; a stream following a run
  another process drives (0e6c0da).
- **Upgrades.** A recalibration of the previous release's severity model, left on the shared
  volume, overrode a newly shipped model for good. It is now ignored at start and on reload
  (ec76e30), and the runbook has an upgrade procedure (ca01617).
- **Azure** could not send approved messages: the templates passed no webhook settings. They are
  now optional Key Vault secrets (ceb5b34).
- **Docs and setup:** the self-hosted NIM's chat model is documented and checked; compose forwards
  either spelling of the Gemini key; `.env.example` names every setting the code reads; the
  runbook covers tenancy, key rotation and token streaming with a separate worker; CI runs the
  fast tests on Python 3.12 (320afe1, ca01617, ceb5b34).
- **Recorded rather than built:** the planner does not replan on a failed validation or low
  severity confidence, and the AG-UI endpoint sends state snapshots, never deltas (README
  limitations). The FAQ no longer says lines are redacted before storage (a6589b4).

### Aesthetics, motion and cleanliness

- **Layout:** memory rows and the example run's claims wrap on phones; chart and graph labels are
  readable on a phone, measured on the built page; skeletons show in both themes; the hero splits
  into two panels only where its cards fit (7fa271f, 48fdfe9, 0ed9407).
- **Type and colour:** small headings use Inter and page titles the light serif; "Needs review"
  uses the forest pill of the main action; night selections show; risk no longer borrows the
  severity colours (7fa271f, 48fdfe9).
- **Motion:** the rule trace fades in place instead of animating its height; rolling numbers drop
  their soft edges at rest; the phone landing page loads lighter fonts (ea9f4dc, 7fa271f). Pulses
  that run while work is under way stay on purpose: they stop when the work ends, and under
  reduced motion.
- **Leftovers:** unused hooks, UI parts and tokens, two settings nothing could use, a dead
  backdrop colour and provider lists that predated Gemini (d893898, ec76e30).

## The third audit: stress, motion and breaking the UI

Before the public demo went up, a third round pushed every part past its normal load, using
installed agent skills as the rulebooks:
- Emil Kowalski's design-engineering skills (`review-animations`, `improve-animations`,
  `animation-performance`, `break-ui`);
- Addy Osmani's web quality skills;
- Vercel's deploy skill.

Each skill is pinned to a reviewed commit in `.claude/skills.lock.tsv`.

### The API under load and hostile input

- **What was tried.** A harness drove the demo image with:
  - requests at and past every size limit;
  - NUL, lone-surrogate, right-to-left, emoji and deeply nested bodies;
  - wrong types and hostile paths;
  - twenty simultaneous approvals of one run and forty readers on one run's live stream;
  - malformed MCP, A2A, AG-UI, Ask ARIA and Alertmanager messages;
  - a burst of reads past the rate limit.

  It ran again inside a free plan's limits: a tenth of a CPU and 512 MB.
- **What held.**
  - No request got a server error, and none hung.
  - Exactly one of the simultaneous approvals won; the rest got 409.
  - Every stream reader received the whole run, and every 429 said when to retry.
  - The API stayed healthy throughout.
- **Fixed: a request is stored no larger than a run reads** (7d1d732). A run reads its first 20,000
  lines, cut at 2,000 characters, but a request kept every line it was sent, in the run row and in
  every checkpoint. One oversized request through the API could fill a small server's memory and
  disk. The runner now trims a request to the per-run cap when it records the run, and the plan
  still says how many lines came in and how many were dropped.
- **Fixed: the demo's limits** (474fe75). A request to the public demo may carry at most 8 MB, as
  through the console, and runs go one at a time, so several large ones arriving together stay
  inside a free plan's memory.

### Motion, against Emil Kowalski's standards

A review measured every animation at four times CPU slowdown, on a phone and a desktop, with
reduced motion and with rapid interruption. The six chosen animations stay, retuned:

- **Severity stamp:** a short ease-out press replaces the ease-in fall.
- **Ghost bloom:** grows quickly from a dot, shrinks back faster and is instant for keyboard focus.
- **Sliding pills:** each move starts from where the pill is drawn, so a quick second move turns it
  around instead of jumping.
- **Landing evidence sweep:** now a transition that reverses mid-way.
- **Run page's evidence pass:** shorter, with a capped stagger.
- **Hero entrance:** a tighter stagger, and only on screens wide enough to see it.

Other motion fixes:

- The command palette and shortcuts sheet open without animation, since they open from the
  keyboard many times a day.
- Popovers, menus and selects grow from their trigger.
- The navigation sheet eases like a drawer.
- Dialog entrances no longer animate `filter`, which kept them off the compositor.

### Breaking the UI with worst-case data

A pass fed the console realistic worst cases at 320, 768 and 1440 px in both themes:
- titles and log tokens with no spaces (stack frames, URLs);
- right-to-left text, emoji and zalgo;
- more than 200 runs;
- double clicks;
- an API that stops.

It fixed:

- **Long tokens no longer widen pages.** A run's error, the incident list, memory, Ask ARIA's
  question and run picker, the evidence panel's title and its unpin button, and run headers now
  wrap such tokens instead of scrolling sideways. The evidence hover card scrolls within the screen.
- **Double clicks act once.** Deleting a run, starting a fork and reviewing each send one request
  however fast the clicks come.
- **Review outcomes appear.** Approving or rejecting now shows its outcome, including messages that
  could not be delivered. The review panel closing as the run moved on had swallowed it.
- **The overview counts past 200 runs.** Runs waiting for review and failed runs are counted by
  their own queries, and a list that stopped at its limit says "+".
- **Durations carry over.** For example, "4 min" no longer reads as "3 min 60 s", and long ones read
  in hours.

What held: escaping (HTML and Markdown show as text everywhere), right-to-left and emoji text, every
empty state, the new-triage form's limits and double-submit guard, outage and recovery, keyboard
focus, 200% zoom and reduced motion.

## What was left

These are recorded rather than fixed, because each needs a design change, infrastructure or an
owner's decision. The [threat model](threat-model.md) lists the security residuals in detail.

- **A fork's history** also lists the checkpoints its parent reached after the fork point, because
  the whole thread is copied; copying only the fork point's ancestors needs a checkpointer change.
- **Streams and slow clients.** Event streams have no per-caller cap, and slow-header connections
  are held open. Front the API with a proxy that enforces these limits. (A stream now ends when its
  run is deleted, and after an hour.)
- **Stored raw input.** Titles, alert names and ticket fields are cleaned when a run is created, but
  the run record and its first checkpoint keep the log lines as sent, and nothing purges old runs.
  Store only the redacted batch, or encrypt the request, and add a retention job.
- **Decisions for the owner.** A window that matches no rule and sits outside the model's range is
  rated by the conservative policy, which can mean SEV1 pending review; changing that is a policy
  choice, not a bug. The Azure SQL free offer pauses the database when its monthly allowance runs
  out (`ARIA_SQL_FREE_LIMIT`); billing past it instead is a cost choice.
- **The model's training range.** Windows much busier than the scenarios it learned from (real HDFS
  traffic, for example) are rated by the rules and confirmed by a person until the model is
  retrained on the deployment's own windows.
- **Smaller issues:** the injection detector misses some spaced-out, homoglyph and role-play
  variants; the console's benign Cocoa sample is rated SEV2, because a `CrashReporter` file path
  matches the crash keyword (fixing the keyword changes a model feature, so it needs retraining and
  a new evaluation); the web CSP needs `'unsafe-inline'` for prerendered pages; MCP log search
  scans without an index; and images are pinned by tag, not digest.
- **Smaller UI items:** "incident" names both the list of triage runs and the past incidents in
  memory (renaming the list is a product decision).
- **From the second audit:** a title that reads like an instruction is dropped without a note (alerts and tickets get one); a refused
  review's reason stays on the run until the next review; searches in non-Latin scripts find
  nothing, because the index splits ASCII words; Azure SQL and Azure OpenAI with managed identity
  run only in deployments, not in CI; and the graph's timeout and cache policies have no tests
  (its retry policy, the router's rerank failover, A2A cancel and the runner's crash handler now
  do).
- **From the third audit:**
  - **Edit dialog:** it has no client-side limits, and the server's limit messages read as
    jargon.
  - **Focus after dialogs:** closing the edit or reject dialog returns focus to the page, not to
    the button that opened it.
  - **API status:** the sidebar's status can lag by up to half a minute.
  - **Typing after a huge paste:** typing in the log box slows down.
  - **Command palette:** it searches only the newest runs.
  - **Evidence chips:** hovering one re-renders every chip.
  - **Run page's step graph:** it measures on every scroll.
- **Motion decisions for the owner:**
  - stamp the severity only when it arrives live or a reviewer corrects it;
  - drop the rolling numbers on the console's evaluation page;
  - play the run page's evidence pass once per pinned citation rather than on every hover.
- **Display decisions for the owner:**
  - when a refresh fails, keep the last incident list on screen;
  - tell runs with identical titles apart;
  - decide whether a confidence of 0.995 should read "100%";
  - the chat defaults to the HDFS format, while New triage defaults to Generic.
- **For the owner:** the live LLM evaluation ran on Gemini's free tier; a larger run on a paid
  plan would give steadier numbers. Zenodo and Hugging Face are reachable now: the
  [data card](data-card.md#found-later-for-the-next-round) lists the sources to add next, with
  their checksums. The build brief's checklist is the owner's specification, so it was left as
  written, though the build has drifted from it (light, hex colours rather than dark-first OKLCH).

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
frozen-frame check of the severity stamp. CI runs all of these except `make eval` on every pull
request and every push to main, with the Lighthouse gate and the video render; `make eval` runs by
hand, and CI's smoke gate checks the published thresholds.
