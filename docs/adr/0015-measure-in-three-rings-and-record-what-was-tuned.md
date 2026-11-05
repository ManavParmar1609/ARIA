# 0015. Measure in three rings, and record what each suite was tuned on

## Status

Accepted.

## Context

ARIA's held-out severity score used fresh windows of the systems, failure modes and pools of real
lines the model was trained on: training, calibration and test differed only by random seed. That
catches regressions, but it cannot say how ARIA does on a system it has never seen, which is the
question anyone deploying it asks. Two real-data suites also shared lines with training. A
regression on OpenStack, where the retrained model rated healthy runs SEV1, showed what this hides.

Small test sets make the problem worse: a handful of serious windows supports a much weaker claim
than its point estimate, and a change chosen by looking at a test set is no longer tested by it.

## Decision

**Three rings** ([`rings.py`](../../src/aria/evals/rings.py)):

- **A, familiar systems:** the seed-disjoint test, kept as CI's tripwire and never quoted as
  generalisation.
- **B, systems and failure modes ARIA has never seen:** leave one system out, and leave one
  failure mode out. For each held-out group the model, its regularisation (chosen by
  cross-validation that holds out whole systems), its temperature and its conformal thresholds
  are fitted again on the other groups only. Every window is scored once, by a model that never
  saw its group. The rules and floors are not refitted: they are fixed by hand and apply
  everywhere.
- **C, real data:** every real-data suite, beside an overlap table wherever the training pools
  hold the suite's lines. BGL, whose lines and alert-tag rubric are in training, is rated twice:
  by the shipped model and by one fitted without any BGL window. HDFS, Hadoop and OpenStack share
  lines with training too; today they are rated by the shipped model and publish the overlap, and
  rating them with a model fitted without their lines is the next step. New domains (security
  alerts, microservice faults, Kubernetes incidents, Jira tickets) share no lines with training
  and join ring C as they are added.

**Honest statistics** ([`stats.py`](../../src/aria/evals/stats.py)): the headline is the
severe-miss rate (a true SEV1 or SEV2 rated SEV3 or SEV4) with an exact one-sided Clopper-Pearson
upper bound. Wilson intervals, exact McNemar tests, bootstraps that resample whole incidents or
systems, and Holm's correction stand behind the comparisons. Over-triage and deferral to a person
are reported as the price of the headline.

**A registry of what was tuned on what** ([`config/eval_registry.yaml`](../../config/eval_registry.yaml)):
each suite is `untouched`, `seen` (looked at during development) or `tuned` (a change was chosen
by looking at it), with the date. The report prints it beside the numbers.

**A fixed way to choose changes:** rules, lexicon, thresholds and model settings are chosen only on
validation seeds 51-56, never on the published test seeds 41-42. A candidate is scored on familiar
systems (ring A) and on every system held out in turn (ring B), with one cost that weighs a severe
miss four times, any other under-triage twice and over-triage once. A candidate is adopted only if
it lowers the ring B cost without raising the ring A cost, a rule set before the candidates run.

## Alternatives considered

- **Random cross-validation over windows.** Windows of one system share templates and lines, so
  random folds leak the system into training and flatter the model.
- **A time split alone.** Most Loghub samples are short and not continuous across systems, so a
  time split cannot hold a whole system out.
- **Report ring A only, with a caveat.** The caveat does not travel with the number.

## Consequences

- The published numbers for new systems are lower than the old held-out score, and say so.
- Evaluation takes longer: ring B refits the model once per held-out group.
- A change that helps new systems but hurts familiar ones is not adopted, however principled it
  looks. Counting corrected hardware errors apart from failures was the first such change.
- A suite looked at while ARIA changes stays marked, so its numbers are read as development
  results until fresh data replaces it.
