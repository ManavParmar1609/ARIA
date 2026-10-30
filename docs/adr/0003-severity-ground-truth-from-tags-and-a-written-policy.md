# 0003. Severity ground truth from dataset tags and a written policy

## Status

Accepted.

## Context

The pitch quoted a severity accuracy with nothing to measure it against. Public log datasets carry
no incident severities, and most Loghub systems are published as samples that are not contiguous
in time, so windows cut from them are not real incidents. If ARIA's own rules produced the labels,
scoring the rules against them would be circular.

## Decision

- **BGL windows** are labelled from the alert tags that system administrators assigned to
  BlueGene/L log lines (Oliner and Stearley, "What Supercomputers Say", DSN 2007). A rubric in
  [`bgl_alert_impact.yaml`](../../config/labeling/bgl_alert_impact.yaml) maps each tag to an
  impact class (critical, major or minor), and window rules turn the tags present, and how many
  nodes they reach, into SEV1 to SEV4 ([`labels.py`](../../src/aria/data/labels.py)).
- **Other systems** are labelled by the scenario policy in
  [`scenarios.yaml`](../../config/scenarios.yaml): a base severity per failure mode, escalated by
  how many nodes are affected or how fast errors arrive. This is ARIA's written domain judgement,
  not a dataset annotation, and results report which labels came from where.
- **The runtime never sees labels.** Severity rules read log text, levels, rates and alerts, never
  alert tags, so the benchmark does not grade the rules against themselves.
- **Windows are semi-synthetic.** The [scenario builder](../../src/aria/data/scenarios.py)
  composes real lines from the [Loghub](https://github.com/logpai/loghub) samples into timed
  windows (choosing nodes, rates and timestamps) and marks every scenario `synthetic=True`.
- **Splits use disjoint seeds** ([`training.py`](../../src/aria/severity/training.py)): train 11
  to 14, temperature 21, conformal 31 and 32, test 41 and 42. Incident memory is seeded from 51
  and 52. Every window goes through the production parser and rules, so training sees exactly the
  features the running system computes.

## Alternatives considered

- **Label windows with ARIA's rules or an LLM.** Circular: it grades the system against itself.
- **Use only the contiguous BGL log.** It has the administrators' tags but only one system, and
  its windows are not independent; it is better as a real-data check than as the only labels.
- **Hand-label windows.** Not feasible at the size of the evaluation, and still one team's
  judgement.

## Consequences

- Every published number describes ARIA on this semi-synthetic distribution, not its accuracy on
  production incidents. Reports, incident memory and results label synthetic data as such.
- The scenarios reuse a few thousand public lines, so templates repeat across windows more than
  in a real fleet, and a policy label is easier to learn than a real severity.
- Changing the policy or the rubric changes the labels. Both are versioned files, and the model's
  metadata records the label sources, seeds and rules version it was trained on.

**Update, 2026-10-30.** The full BlueGene/L log now comes from a checksum-pinned public copy, and
ARIA is also scored on its contiguous windows, labelled by the same rubric
([evaluation.md](../evaluation.md#real-logs-a-supercomputers-alert-tags)). On that real log the
rules alone did better than the rules and the model trained on these semi-synthetic windows, so
the semi-synthetic results above are not a promise about real fleets. The decision stands for
training: real tags label the BGL scenarios, and a written policy labels the rest.
