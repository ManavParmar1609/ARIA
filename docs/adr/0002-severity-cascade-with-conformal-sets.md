# 0002. Severity: rules, a calibrated model and a conformal set, then the LLM

## Status

Accepted.

## Context

The original pitch called an LLM whenever rule confidence fell below 85%. A rule score is not a
probability, so a fixed threshold on it says nothing about how often the decision is wrong.
Mistakes also cost more in one direction: rating a SEV1 as SEV3 (under-triage) does more harm
than the reverse. And an LLM given a free choice of severity can be talked into anything by text
planted in the logs.

## Decision

[`SeverityEngine`](../../src/aria/severity/engine.py) runs a cascade, and
[`policy.py`](../../src/aria/severity/policy.py) makes the decision:

1. **Rules.** Declarative rules in [`severity_rules.yaml`](../../config/severity_rules.yaml),
   evaluated by [`rules.py`](../../src/aria/severity/rules.py), read only what ARIA computes from
   the window (counts, rates, spread, keyword categories, component criticality) plus firing
   alerts. A rule either adds to a class's score or sets a floor the final severity can never go
   below. Every hit becomes citable evidence.
2. **Calibrated model.** A multinomial logistic regression over the window's features, the rule
   scores and the floor ([`model.py`](../../src/aria/severity/model.py)). One temperature,
   fitted on a held-out split, calibrates it (temperature scaling,
   [Guo et al., 2017](https://arxiv.org/abs/1706.04599)). Models are JSON files scored with
   numpy, so loading one cannot run code; with no model file, the engine uses normalised rule
   scores and says so in the evidence.
3. **Conformal set.** A split-conformal threshold fitted on a second held-out split turns the
   probabilities into a prediction set that holds the true class at least `1 - alpha` of the
   time on exchangeable data. This is the least ambiguous set-valued classifier of Sadinle, Lei
   and Wasserman (JASA, 2019), with `alpha` 0.1. Floors then remove classes less severe than the
   floor.
4. **Decision.**
   - A single-class set whose calibrated probability reaches the gate (`auto_confidence`, 0.85)
     is decided without an LLM, as `rules` or `model`.
   - Otherwise the LLM adjudicator ([`adjudicator.py`](../../src/aria/severity/adjudicator.py))
     may choose. Its JSON schema offers only the classes in the set, and its answer is checked
     again: a class outside the set, or a citation of evidence that does not exist, is repaired
     or discarded.
   - With no usable LLM (none configured, budget spent or invalid output), ARIA takes the most
     severe class in the set and flags the run for review.

## Alternatives considered

- **Keep the pitch's gate on rule confidence.** Simple, but its error rate is unknown.
- **LLM-first classification.** Costly per run, hard to audit, and exposed to prompt injection in
  log text.
- **The calibrated model alone.** The evaluation compares it with the full policy; the rule
  floors exist to cut severe under-triage ([results](../evaluation.md#severity)).

## Consequences

- Every decision records `decided_by` (`rules`, `model`, `llm`, `fallback`, or `human` after a
  reviewer's edit), the probabilities, the set and the rule hits. Runs decided without an LLM are
  auditable without reading any model output.
- A confused or compromised LLM can only choose among classes the calibrated stages already
  allow, and never below a floor.
- The 0.85 number survives, but it now gates a calibrated probability, and only for a
  single-class set.
- The coverage guarantee holds only on data like the calibration split, which is semi-synthetic
  ([0003](0003-severity-ground-truth-from-tags-and-a-written-policy.md)).
  [0011](0011-recalibrate-only-the-conformal-threshold-from-reviews.md) recalibrates on reviewed
  incidents for that reason.
- The conservative fallback over-triages when the model is unsure. That is deliberate, and it
  shows up as review load.
