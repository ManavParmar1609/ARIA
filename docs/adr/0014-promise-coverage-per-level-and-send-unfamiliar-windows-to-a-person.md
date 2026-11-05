# 0014. Promise coverage per severity level, and send unfamiliar windows to a person

## Status

Accepted. Supersedes [0011](0011-recalibrate-only-the-conformal-threshold-from-reviews.md) for
models with per-level calibrations; 0011 still applies to model files without them.

## Context

ARIA's prediction set used one threshold for every level, promising that the true level is in the
set 90% of the time. That promise is an average over levels: common, easy levels can carry it
while rare, serious ones fall short. Measured on validation seeds that published results never
use, the set held a true SEV1 or SEV2 well under 90% of the time, and on systems the model never
saw (leave-one-system-out) far less still. A severe miss, a serious incident rated SEV3 or SEV4,
is the error that matters most.

Reviews also fed recalibration in a way that could fool it: an approval counted as confirming
ARIA's level, and a person who approves without checking makes the sets look better calibrated
than they are.

## Decision

**A promise per level** ([`model.py`](../../src/aria/severity/model.py) `Calibration`,
[`conformal.py`](../../src/aria/severity/conformal.py)):

- Each level has its own split-conformal threshold, fitted on calibration windows whose truth is
  that level (class-conditional, or Mondrian, conformal prediction). SEV1 and SEV2 allow a 5% miss
  rate (`severity.serious_alpha`), SEV3 and SEV4 10% (`severity.alpha`).
- Sets are ordered: a set holding SEV1 and SEV3 also holds SEV2. Filling a gap only adds levels,
  so no promise weakens.
- A guard from conformal risk control adds the likelier serious level when the serious levels'
  total probability is high enough and neither made the set. It is the loosest guard that
  certifies a severe-miss rate of at most `severity.severe_miss_risk` (5%) on calibration-like
  data. When the per-level sets already meet that, no guard is needed and the calibration records
  the certificate.
- The model file keeps each level's sorted calibration scores, so a threshold at any miss rate can
  be recomputed without the training data.

**Windows ARIA should not decide alone** (`SeverityEngine._novelty`, `trained_on`). A person
confirms, and nothing is decided automatically, when any of these hold:

- the window's features are past the training range (the existing guard; the rules then set the
  levels);
- its mix of features is further from the training windows than nearly all held-out windows
  (a conformal p-value on a shrunk-covariance Mahalanobis distance, below 1%);
- the share of its log patterns that are new to the system is likewise extreme;
- the set is empty or holds every level;
- the model never trained on the window's system.

For the two "unusual" signals, the levels the rules leave open also join the set, because the
model's probabilities are least trustworthy there.

**A language model's pick below a possible serious level needs a person.** If the set holds SEV1
or SEV2 and the adjudicator picks SEV3 or SEV4, the run asks for review, since that is where a
severe miss would hide.

**Blind checks, not approvals, recalibrate** ([`recalibration.py`](../../src/aria/severity/recalibration.py)).
A blind check is a person rating an incident before seeing ARIA's level. After each one, in the
order they arrive, the rated level's miss rate moves toward its target: down when the set missed
the person's level, up a little when it held it (adaptive conformal inference, Gibbs and Candès,
2021). Over any sequence of checks, the share of misses exceeds the target by no more than a known
amount that shrinks as checks accumulate. Every 100 further checks of a level replace that level's
calibration scores with the checks' own. The miss rate may dip below zero, meaning "never rule this
level out", because clipping it would forget misses and break the bound.

**Drift, without labels** ([`drift.py`](../../src/aria/severity/drift.py)). Per system, the levels
ARIA decided on its recent runs are compared with its earlier runs by the population stability
index, against the cut-off sampling noise alone would pass one time in twenty (Yurdakul, 2018).
`/metrics` counts decisions by level, set sizes and each reason a person was asked to confirm.

## Alternatives considered

- **A second calibration for systems the model never trained on**, fitted on windows scored by
  models trained without each window's system (the two-layer view of Dunn, Wasserman and Ramdas,
  2022). On validation seeds its sets usually held most of the four levels, so the conservative
  fallback rated nearly every window SEV1. Fitting only the guard that way missed its own target
  on held-out systems. Systems differ too much for one system's calibration to transfer, so ARIA
  sends such windows to a person instead and publishes how it does on unseen systems.
- **One tighter threshold for every level.** It widens the sets for every level to protect the
  rare ones, the cost per-level thresholds avoid.
- **Keep counting approvals.** Cheap, but it rewards rubber-stamping with narrower sets.

## Consequences

- Severe misses fall on familiar and unseen systems alike; over-triage rises, which the
  conservative policy accepts as the price. The published numbers are in
  [evaluation.md](../evaluation.md).
- The policy's macro-F1 falls with that over-triage, below the floor CI's smoke gate set for the
  old engine. The owner re-based the gate rather than tune on a test seed to clear it
  ([`config/eval_thresholds.yaml`](../../config/eval_thresholds.yaml)):
  - the old floor now applies to the calibrated model alone;
  - the policy has a lower floor and a cap on over-triage;
  - the cap on serious misses is unchanged.

  A weaker model, or a policy that over-triages more, still fails CI.
- Logs from a system ARIA never trained on always reach a person, however confident the model is.
- Recalibration needs blind checks, which take a reviewer's time; until they come, the shipped
  calibration stands.
- Every setting here was chosen on validation seeds 51 to 56 and on held-out systems, never on the
  published test seeds or the real-data suites.
