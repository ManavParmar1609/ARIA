# Model card

This card covers four things:

- the log-severity model that ARIA trains, `severity_log`;
- the decision policy that turns its output into a severity;
- the ticket models, which are untrained in this build;
- the third-party models ARIA calls but does not train.

It follows the spirit of [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993)
(Mitchell et al., 2019). The data behind the model is described in the [data card](data-card.md).

## Model details

| | |
|---|---|
| Name | `severity_log` |
| Committed version | `severity-log-20261029-a362d541`: the `version` field of [`models/severity_log.json`](../models/severity_log.json) |
| Task | Rate one window of log lines, plus any firing alerts, from SEV1 to SEV4 |
| Type | Multinomial logistic regression on standardised features, with temperature scaling and split-conformal prediction sets |
| Output | A calibrated probability for each of the four classes, and a prediction set that targets 90% coverage (alpha 0.1) |
| Rules version | `2026.10.2` ([`config/severity_rules.yaml`](../config/severity_rules.yaml)), recorded in the model's metadata |
| Format | JSON (`aria.linear_model.v1`): coefficients, scaler statistics, temperature, conformal threshold and metadata. Inference is plain numpy, and loading a model file cannot run code. |
| Code | [`src/aria/severity/`](../src/aria/severity/): `model.py`, `training.py`, `policy.py`, `engine.py` and `recalibration.py` |
| Training data | **Semi-synthetic** windows built from real Loghub lines ([data card](data-card.md)) |
| Licence | The code is MIT. The model is trained on Loghub-derived data, and the Loghub terms still apply to it. |

The severity levels are:

- SEV1: a widespread outage or data-loss risk;
- SEV2: major degradation or a failing critical component;
- SEV3: contained errors;
- SEV4: noise.

## How a severity is decided

The model is one stage of a policy
([`src/aria/severity/policy.py`](../src/aria/severity/policy.py)). The stages run in this
order:

1. **Rules score each severity, and some set a floor.** The rules file holds 22 scoring rules
   and 4 floor rules. Three floors keep signals at SEV2 or worse: data-integrity errors
   (corruption, data loss, missing blocks), a crashing critical component, and a firing
   critical alert. The fourth keeps units of work that stopped partway with no error logged
   (parsing/flows.py) at SEV3 or worse: the model, trained on windows that log their failures,
   reads such a window as noise. A severity's summed rule weight must reach its activation threshold, so one
   decisive SEV1 rule is not outvoted by the weaker SEV2 rules that a severe incident also
   trips.
2. **The model gives calibrated probabilities.** It reads the window's features, including the
   rules' output. The prediction set holds every class whose probability is at least 1 − q,
   where q is the conformal threshold. If no class clears it, the most likely class stands
   alone and the set is marked empty.
3. **Floors narrow the set.** They remove every class less severe than the floor.
4. **A confident one-class set is decided without an LLM.** This happens when the model gives
   the class at least 0.85 (the `gate` in the rules file), or when a floor alone settled it.
   `decided_by` is `rules` when a floor settled it or the rules agree, and `model` otherwise.
   Both are auditable.
5. **Otherwise an LLM may choose, but only within the set.** The severity enum in its JSON
   schema is the set, and its answer is checked again: the class must be in the set and every
   cited evidence ID must exist. `decided_by` is `llm`. These decisions are not auditable, and
   they are flagged for review when the set holds three or more classes.
6. **Without an LLM, ARIA takes the most severe class in the set.** This applies when no LLM is
   configured, the run's budget is spent, or the LLM's answers fail validation. The severity is
   flagged for review, and `decided_by` is `fallback`. Under-triage costs more than
   over-triage.

Two cases follow from this:

- **No model file.** ARIA runs on rules only. Probabilities are normalised rule scores, the set
  holds every class with a probability of at least 0.2, and the version reads
  `rules-only:<rules version>`.
- **Offline.** The adjudicator's provider chain has no offline fake provider. So offline runs,
  and the published offline evaluation, always end at step 4 or step 6.

Every assessment records the following, and the run view shows all of it:

- the probabilities;
- the prediction set;
- the floor;
- each rule hit, as a piece of evidence;
- the model version;
- `decided_by`.

## Inputs

The model reads 38 features of one window
([`src/aria/severity/features.py`](../src/aria/severity/features.py)). The parser computes them
from redacted message text, levels, timestamps, nodes and components, plus any firing alerts.
Lines quarantined as possible prompt injection are left out first. No feature reads dataset
labels or BGL alert tags.

| Group | Features | Scale |
|---|---|---|
| Volume and spread (16) | Events, error events, events per minute, peak errors per minute, distinct nodes, nodes with errors, templates, novel templates, novel error templates, peak warnings per minute, nodes with warnings, novel warning templates, critical components, firing alerts, critical alerts, warning alerts | log(1 + x) |
| Ratios (3) | Error ratio, node spread, highest criticality among components logging errors | 0 to 1 |
| Shape (5) | Burst score (capped at 50, divided by 10), persistence in minutes (log scale), shares of WARN, ERROR and FATAL lines | As listed |
| Keyword categories (9) | Crash, data risk, unavailable, resource, security, hardware, storage, network, degradation ([`config/lexicon.yaml`](../config/lexicon.yaml)) | log(1 + matching lines) |
| Rules (5) | The rules' smoothed probability for each severity, and the floor rank (0 is a SEV1 floor and 3 a SEV4 floor; 4 means no floor) | 0 to 1; 0 to 4 |

Two of these depend on configuration and history:

- **Component criticality** comes from
  [`config/service_catalog.yaml`](../config/service_catalog.yaml). In a real deployment that
  file should come from the deployment's own service catalog.
- **Novelty features** compare a window with the routine templates ARIA has already seen. A new
  deployment starts from the history that `aria seed` loads.

## Training

- **Data.** The semi-synthetic scenario suite, built from real lines in the Loghub 2k samples.
  - Each seed contributes 6 windows per failure mode and 3 quiet windows per system.
  - The splits use separate seeds: train 11–14, temperature 21 and conformal 31–32.
  - The committed model's metadata records 660 training, 165 temperature and 330 conformal
    windows. The per-split label counts are in
    [`models/severity_log.report.json`](../models/severity_log.report.json) and in the data
    card.
  - Every window goes through the production parser and rules, so training sees exactly the
    features a run computes.
- **Fit.** scikit-learn's logistic regression on standardised features, with balanced class
  weights.
  - C is chosen from {0.03, 0.1, 0.3, 1, 3} by stratified cross-validation on the training
    split (up to 4 folds), scored by log loss.
  - The committed model chose C = 3.
  - Classes absent from the training data would get almost no probability.
- **Calibration.** A single temperature that minimises negative log-likelihood on the
  temperature split ([Guo et al., 2017](https://arxiv.org/abs/1706.04599)). It corrects over-
  and under-confidence without changing which class ranks first.
- **Conformal prediction.** Split-conformal prediction with the least ambiguous set-valued
  classifier ([Sadinle et al., 2019](https://arxiv.org/abs/1609.00451)), fitted on the
  conformal split.
  - The threshold q is the finite-sample-corrected (1 − alpha) quantile of 1 − p(true class).
  - With alpha 0.1 ([`config/aria.yaml`](../config/aria.yaml)), the sets hold the true class at
    least 90% of the time, but only on data exchangeable with the conformal split.
- **Version.** `severity-log-<date>-<first 8 hex digits of a SHA-256 of the coefficients>`.
- **Retraining.** `make train` (or `aria train severity`) writes the model and its training
  report.

## Recalibration on reviewed incidents

The coverage guarantee holds only on data like the calibration split. A deployment's own
incidents differ from the semi-synthetic windows, so ARIA recalibrates on them
([`src/aria/severity/recalibration.py`](../src/aria/severity/recalibration.py)).

**What is recorded.** Every human review stores the run's model input (the 38 features) and the
severity the reviewer settled on:

- an approval confirms ARIA's severity, and an edit corrects it;
- a rejection settles nothing and is left out;
- runs approved automatically, because approval was turned off, are not recorded at all.

**When it runs.** A background job checks every `severity.recalibrate_check_s` seconds, where
runs execute: in the API in in-process mode, or in `aria worker` in external mode.

- The default interval is 600 seconds, and 0 turns the job off.
- It recalibrates once `severity.recalibrate_after` new reviews have gathered since the loaded
  model was calibrated (default 30, minimum 10).
- New reviews are counted against the model file's own record, so a model restored from an
  older file recalibrates again from the shared database.
- `aria train recalibrate [--min-new-reviews N] [--dry-run]` does the same by hand. With
  `--dry-run`, it reports the effect without saving anything.

**What it does.**

1. It recomputes the conformal threshold on all reviewed incidents, not just the new ones.
2. It writes the model atomically under a new version to `ARIA_MODELS_DIR` (`models/` in a
   checkout; the shared `/var/lib/aria/models` volume in containers), and keeps the previous
   file beside it as `severity_log.<previous version>.json`. The trained model that ships with
   the code is never overwritten there; engines read it until the first recalibration.
3. It marks the reviews as used.

Running engines, in every container that shares the volume, reload the file when it changes.

**What moves and what does not.** Only the threshold moves; alpha is taken from the config.
The coefficients, scaler and temperature stay as trained. So recalibration can widen or narrow
the prediction sets, and with them how often ARIA asks for review. It cannot change which class
the model ranks first.

**Versions.**

- A recalibrated model is named `<trained version>-recal<n>`, where n is the number of reviewed
  incidents it used.
- Its metadata gains `trained_version`, `recalibrated_from`, `recalibrated_at`, `n_reviewed`,
  `coverage_before` and `coverage_after`.

**Caveats.** Reviewed incidents are not a random sample, and every approval counts as a
confirmation. The guarantee is only as good as the reviews.

**Rolling back.** Copy the kept file back over `severity_log.json` in `ARIA_MODELS_DIR`, or
delete that file to return to the trained model. Unless
`recalibrate_check_s` is 0, the job may recalibrate again at its next check if enough reviews
have gathered. The [ops runbook](ops-runbook.md) has the operational steps.

## Metrics

Below are the calibrated model, the model with rule floors and ARIA's full offline policy,
compared with simple baselines on the held-out test seeds (41 and 42). `make eval` generates
this section; the method and the other suites are in [evaluation.md](evaluation.md).

<!-- generated:severity-metrics -->
Generated by `make eval` at commit `23d7f36`; do not edit by hand. The data is **semi-synthetic**: real lines from the public Loghub samples, composed into incidents by ARIA's scenario builder, on held-out seeds 41, 42. These numbers show how ARIA behaves on that distribution, not its accuracy on production incidents.

### Held-out results

330 held-out windows. Labels: SEV1 34, SEV2 80, SEV3 95, SEV4 121.

| Method | Accuracy (95% CI) | Macro-F1 (95% CI) | Weighted kappa | Under-triage | SEV1/2 rated SEV3/4 |
|---|---|---|---|---|---|
| ARIA policy (offline) | 90.3% (87.3–93.3%) | 0.880 (0.834–0.917) | 0.916 | 3.0% | 3.5% |
| Calibrated model + rule floors | 90.0% (87.0–93.0%) | 0.878 (0.834–0.916) | 0.914 | 3.9% | 6.1% |
| Calibrated model only | 90.6% (87.3–93.6%) | 0.883 (0.841–0.921) | 0.912 | 4.5% | 8.8% |
| Rules only | 58.2% (52.7–63.6%) | 0.524 (0.469–0.579) | 0.554 | 17.0% | 22.8% |
| Keyword categories only | 41.2% (36.1–46.4%) | 0.396 (0.340–0.448) | 0.249 | 20.9% | 18.4% |
| TF-IDF + logistic regression (raw text) | 84.5% (80.9–88.2%) | 0.827 (0.782–0.868) | 0.923 | 6.4% | 14.0% |
| Majority class | 36.7% (31.5–41.8%) | 0.134 (0.120–0.147) | 0.000 | 63.3% | 100.0% |

The text baseline reads each window's raw lines, minus the alert tag that BGL and Thunderbird lines open with: the BGL labels come from that tag.

Calibration of the model's probabilities: ECE 0.027, Brier 0.138.

Risk–coverage (the calibrated model answering only its most confident windows): 0.0% error at 50.0% coverage, 1.5% error at 60.0% coverage, 2.2% error at 70.0% coverage, 2.3% error at 80.0% coverage, 5.4% error at 90.0% coverage, 9.4% error at 100.0% coverage; AURC 0.016.

Conformal prediction sets (alpha 0.1, target coverage 90.0%): coverage 91.8% before the rule floors, 91.2% after; mean set size 1.021.

Automation: 83.0% of windows were decided without review, with 96.0% accuracy; the rest were flagged for review (62.5% accuracy for the conservative choice).

| System | Windows | Accuracy | SEV1/2 rated SEV3/4 | Labels from |
|---|---|---|---|---|
| android | 18 | 100.0% | 0.0% | scenario_policy |
| apache | 18 | 100.0% | 0.0% | scenario_policy |
| bgl | 66 | 92.4% | 4.0% | bgl_alert_tags |
| hadoop | 30 | 96.7% | 0.0% | scenario_policy |
| hdfs | 18 | 100.0% | 0.0% | scenario_policy |
| hpc | 42 | 71.4% | 3.5% | scenario_policy |
| linux | 18 | 88.9% | 20.0% | scenario_policy |
| mac | 18 | 100.0% | 0.0% | scenario_policy |
| openssh | 18 | 77.8% | 0.0% | scenario_policy |
| openstack | 18 | 83.3% | 0.0% | scenario_policy |
| proxifier | 18 | 100.0% | 0.0% | scenario_policy |
| thunderbird | 18 | 100.0% | 0.0% | scenario_policy |
| zookeeper | 30 | 83.3% | 0.0% | scenario_policy |
<!-- /generated:severity-metrics -->

What each row measures:

- **ARIA policy (offline).** The full policy with no LLM: decide a confident one-class set,
  otherwise take the most severe class in the set. This is what an offline deployment does. An
  LLM can only choose inside the same sets.
- **Calibrated model + rule floors.** The most likely class that the floors allow.
- **Calibrated model only.** The model's top class.
- **Rules only.** The rules' own severity.
- **Keyword categories only.** The most severe keyword category with at least 3 matching lines.
- **TF-IDF + logistic regression.** A bag of words over the raw window text, trained on the
  training seeds, with a fixed regularisation strength. It strips the sysadmin alert tag that
  raw BGL lines open with (the tag defines the BGL labels), as ARIA's features never read it.
  Its tokens are words of three or more letters, so it cannot count hosts.
- **Majority class.** The most common training label.

Severity inside complete runs, with an LLM and without, is reported in the
[end-to-end sections](evaluation.md#end-to-end-offline-no-llm-steps) of the evaluation. CI runs
a small, deterministic sample (`make eval-smoke`) against the thresholds in
[`config/eval_thresholds.yaml`](../config/eval_thresholds.yaml), and the build fails on a
regression.

## Intended use

- First-pass severity for windows of logs from systems like those in the catalog, as decision
  support for on-call engineers and SREs.
- Ordering and annotating the review queue. The prediction set and the review flag say when
  ARIA is unsure.
- Always behind human review. Every run pauses for a person to approve, edit or reject the
  report before anything is published or sent. Approval can be turned off, in the settings and
  on the run. Then the report is published, but nothing goes out.

## Out of scope

- Paging, escalating or closing incidents without a person reviewing them.
- Systems and log formats the model has not seen, until it has been recalibrated on reviewed
  incidents from them. They parse with a generic line format, and their features may not mean
  what they meant in training.
- Classifying incidents for regulatory or contractual purposes. The labels follow this
  project's rubric and policy, not any regulator's or contract's definitions.
- Judging people, for example on-call performance.
- Treating the probabilities as calibrated on your own incidents before recalibration.

## Limitations

- **The data.** Training and test data are semi-synthetic, and every split draws from the same
  pools of real lines. The published numbers are not production accuracy; see the
  [data card](data-card.md#known-biases-and-gaps).
- **Features that mirror the generator.** The lexicon's categories and the service catalog's
  criticalities were written for the failure modes the scenario builder composes, and the policy
  labels follow each window's true node count and peak rate, which the features estimate. The
  held-out seeds hold out only each window's composition, so the severity benchmark largely
  measures how well ARIA recovers the generator's own inputs. Test windows that use messages
  training never saw are harder, for ARIA and for the text baseline alike.
- **No untouched test set.** The test seeds (41 and 42) were evaluated during development: the
  parser, features, investigator and label policy changed after runs on them, and CI's smoke gate
  runs on seed 41. Read the severity numbers as development-set results. Their intervals resample
  windows as if they were independent, but windows of one failure mode share a few source
  messages, so the true uncertainty is wider.
- **Prediction sets.** Almost every set holds one label, so coverage sits close to top-1
  accuracy and an LLM adjudicates rarely. The 90% target holds on windows exchangeable with the
  calibration windows; coverage differs by class and falls under a shift.
- **Retrieval scores.** Retrieval filters by system first, and most systems have a single failure
  mode in memory, so many queries cannot miss. Recall@3 here is a hit rate at three, close to what
  a random pick within the system would score.
- **Uneven accuracy.** Accuracy varies by system (see the per-system table above), and the
  conservative fallback over-triages rather than under-triages when the model is unsure.
- **Calibration and coverage.** They hold on the semi-synthetic distribution. On a deployment
  they hold only after recalibration, and only as far as the reviews reflect the truth.
- **What the model sees.** It is a linear model over aggregates of a single window. It sees
  order only through the burst and persistence features, and it does not connect incidents
  across windows.
- **The rules.** The model reads the rules' output, so changing the rules means retraining. The
  rules version is recorded in the model so that a mismatch can be seen.
- **The ticket model.** It is untrained in this build ([below](#the-ticket-models)), so tickets
  add nothing to severity.

## Ethical and operational considerations

- **Under-triage and over-triage.** A missed SEV1 costs more than an unneeded page, and three
  parts of the design lean toward over-triage: the floors, the most-severe-in-set fallback and
  the balanced class weights. Over-triage still costs attention and feeds alert fatigue. The
  benign failure modes and quiet windows exist to measure it. Under-triage rates are reported in
  the [evaluation](evaluation.md#severity).
- **Review and automation bias.** The review screen shows the evidence behind a severity: the
  rule trace, the probabilities and the prediction set. Approvals feed recalibration as
  confirmations, so a reviewer who disagrees should edit the severity rather than approve it.
- **Privacy.**
  - Logs carry personal data. Secrets are redacted before any model sees the text, and e-mail
    and IP addresses are pseudonymised. Hostnames and usernames remain.
  - With a hosted provider (NVIDIA's hosted NIM, Azure OpenAI or another endpoint), redacted
    evidence leaves your network. Where that is not acceptable, use a self-hosted NIM or run
    offline.
- **Prompt injection.**
  - Injected lines are quarantined before features are computed.
  - An LLM can only pick a severity within the calibrated set and never below a floor.
  - See the [threat model](threat-model.md).
- **Data terms.** The model and the seeded memory derive from Loghub data, which is licensed for
  research and academic work.

## The ticket models

[`src/aria/severity/ticket.py`](../src/aria/severity/ticket.py) defines two calibrated linear
models for ITSM tickets, trained on the UCI incident log.

**The models.**

- **Priority.** Predicts a ticket's final priority, with a conformal set. Priorities 1–4 map to
  SEV1–SEV4, and priority 5 maps to SEV4.
- **SLA breach.** Estimates the risk that the ticket breaches its SLA.

**Inputs.** Only fields known when the ticket is opened: category, subcategory, symptom,
contact type, location, first assignment group, impact, urgency, the knowledge and
priority-confirmation flags, and whether the ticket was opened in business hours or at the
weekend. A value seen on fewer than 20 training tickets is folded into "other".

**The matrix.** An impact × urgency matrix is learned from the training tickets (the most common
final priority for each pair). It is reported beside the prediction as the auditable rule.

**Splits.** By open time:

- the oldest 70% train;
- the next 15% calibrate, split in time order between temperature and conformal;
- the newest 15% are held out.

Neither outcomes nor future tickets reach training.

**Status: untrained.** The UCI log could not be downloaded in the build environment, so there
is no `models/severity_ticket.json`.

- `POST /api/v1/tickets/assess` answers 503.
- The outcome statistics of similar tickets are empty.
- `make eval` has no ticket suite yet. `aria train tickets` prints metrics for the training and
  conformal splits only, so the held-out split is not scored anywhere.

To train the models once the data is reachable:

```bash
uv run aria data download --source uci-incidents
```

```bash
uv run aria data ingest
```

```bash
uv run aria train tickets
```

## Third-party models ARIA calls

ARIA does not train these models. Which ones run depends on [`config/aria.yaml`](../config/aria.yaml)
and the environment: a provider with no key or endpoint is skipped. `uv run aria providers
check` confirms the configured IDs against each provider's catalog and sends each provider one
tiny request.

| Role | Provider chain | Default model | Verified |
|---|---|---|---|
| Severity adjudicator | `nim-local` → `nim` → `nim-fallback` → `azure` → `openai_compat` (no fake: the policy decides instead) | As for the chat roles below | As below |
| Investigator, reporter, critic, comms and Ask ARIA | The same chain, ending at the deterministic `fake` provider | `nim`: `openai/gpt-oss-20b` (reasoning effort low). `nim-fallback`: `minimaxai/minimax-m3.1-flash`. `azure`: the deployment named `gpt-5.1`. `openai_compat` and `nim-local`: none set. | `nim` and `nim-fallback` answered live calls on 2026-10-29. `azure`, `openai_compat` and `nim-local` are not verified. |
| Embeddings | `nim` → `azure` → `local` | `nim`: `nvidia/nemotron-3.5-embed-1b` (2048 dimensions). `azure`: the deployment named `text-embedding-3-small`. `local`: latent semantic analysis (TF-IDF over words and word pairs, reduced to 128 dimensions) fitted by `aria seed` on the incident corpus. | The NIM model answered live calls on 2026-10-29. The Azure deployment is not verified. |
| Reranking | `nim` | None. Reranking is off until `NVIDIA_NIM_RERANK_MODEL` and `NVIDIA_NIM_RERANK_URL` are set. | Not applicable |
| Content safety | `nim` | `nvidia/nemotron-3.5-content-safety` | **Listed in NIM's model catalog on 2026-10-29, but not called live**, so its verdict format is unverified. The guardrail is off by default (`guardrails.safety_model: false`). |
| Self-hosted NIM | `nim-local`, from the compose `nim` profile | Whatever `NIM_LOCAL_CHAT_MODEL` names. The profile's default image is `nvcr.io/nim/meta/llama-3.1-8b-instruct:latest`. | Not verified |

What these models can and cannot do:

- An LLM never sets severity on its own. It picks within the calibrated set, as described
  [above](#how-a-severity-is-decided).
- LLM-written report text must cite existing evidence and pass validation, and LLM-polished
  messages must follow their audience's rules. Otherwise ARIA keeps its deterministic draft.
- When the content-safety guardrail is on, it reads that text first and fails closed: a verdict
  it cannot read, or a safety model it cannot reach, counts as flagged.
- Per-run budgets cap tokens, cost, latency, steps, tool calls and LLM calls (`budgets` in the
  config). When a budget is spent, the run falls back to the deterministic path.

## Versions and where to find them

- **The trained model.** `version` and `metadata` in
  [`models/severity_log.json`](../models/severity_log.json). The metadata records:
  - the rules version and the seeds;
  - the split sizes and the label sources;
  - `synthetic: true`;
  - when the model was calibrated.

  The training report sits beside it, in
  [`models/severity_log.report.json`](../models/severity_log.report.json).
- **A recalibrated model.** Named `<trained version>-recal<n>`, with the recalibration
  metadata listed above. Each previous version is kept as `severity_log.<version>.json`.
- **Each run.** Every severity assessment records `model_version`, which reads
  `rules-only:<rules version>` when no model file is loaded. Every review stores the model
  version and the model input with it. The run view shows the version under the severity.
- **The API.** `GET /api/v1/feedback` returns `calibration` with these fields:
  - `model_version` and `trained_version`;
  - `recalibrated` and `reviews_in_model`;
  - `reviewed` and `pending`;
  - `recalibrate_after` and `check_interval_s`;
  - `coverage_before` and `coverage_after`.

  The console's settings page shows the same information under "Learning from reviews".
- **The rules.** They carry their own version (`version` in
  [`config/severity_rules.yaml`](../config/severity_rules.yaml)). It is recorded in the model's
  metadata and on every rule-hit evidence item.

## References

- M. Mitchell et al., "Model Cards for Model Reporting", FAT\* 2019. [arXiv:1810.03993](https://arxiv.org/abs/1810.03993)
- C. Guo, G. Pleiss, Y. Sun and K. Q. Weinberger, "On Calibration of Modern Neural Networks",
  ICML 2017. [arXiv:1706.04599](https://arxiv.org/abs/1706.04599)
- M. Sadinle, J. Lei and L. Wasserman, "Least Ambiguous Set-Valued Classifiers with Bounded
  Error Levels", JASA 2019. [arXiv:1609.00451](https://arxiv.org/abs/1609.00451)
- J. Zhu et al., "Loghub: A Large Collection of System Log Datasets for AI-driven Log
  Analytics", ISSRE 2023. [logpai/loghub](https://github.com/logpai/loghub)

See also: the [data card](data-card.md), [evaluation](evaluation.md),
[threat model](threat-model.md), [ops runbook](ops-runbook.md),
[architecture decisions](adr/README.md) and the [README](../README.md).
