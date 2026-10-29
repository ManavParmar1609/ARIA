# 0007. Every report claim cites evidence, with a deterministic fallback

## Status

Accepted.

## Context

An incident report that a reviewer cannot check is worse than none. The pitch promised that every
report field would trace to a tool call, but prose an LLM writes cannot come from a tool call.
Pydantic validation catches malformed output; it does not catch a well-formed report that cites
nothing, invents a number or changes the severity.

## Decision

- **An evidence registry.** Every citable fact (a log template, a rule hit, the model's
  probabilities, a tool result, a similar incident, a hypothesis) gets an id such as `E12` when it
  is produced ([`evidence.py`](../../src/aria/evidence.py)). Every claim, timeline entry and action
  in a report cites ids.
- **A grounded draft always exists.** The [composer](../../src/aria/reporting/composer.py) builds a
  complete report from the evidence with no model: each sentence comes from an evidence item and
  cites it, and each number is copied from it.
- **Deterministic checks** ([`grounding.py`](../../src/aria/reporting/grounding.py)) pass a report
  only when:
  - every claim, timeline entry and action cites evidence that exists;
  - every number in a claim appears in the evidence it cites, allowing for rounding and
    percentages;
  - the severity matches the severity assessment;
  - no text contains a secret or an instruction aimed at a model;
  - every action that names a runbook names a real one, at no lower risk than its step.
- **The writer** ([`writer.py`](../../src/aria/reporting/writer.py)) runs four steps:
  1. With an LLM configured, it asks the model to improve the draft. The router repairs or
     rejects any narrative that fails the checks.
  2. A critic (the LLM when one is configured, an offline lexical check otherwise) reviews each
     claim against its cited evidence, and claims it flags as unsupported, contradicted,
     overstated or uncited are removed.
  3. Final validation runs.
  4. If the LLM's version still fails, ARIA publishes the grounded draft.
- **After a replan, validation is strict.** Number mismatches in actions become errors instead of
  warnings.
- **The same idea applies to comms.** Drafts for responders, stakeholders and the status page
  follow per-audience rules ([`comms.py`](../../src/aria/reporting/comms.py)). An LLM-polished
  draft that breaks them is dropped for the deterministic one.

## Alternatives considered

- **Trust the LLM, with schema validation only.** It catches format errors, not invented content.
- **An LLM judge as the gate.** It is costly, not deterministic and unavailable offline. ARIA keeps
  the deterministic checks as the gate, and lets the critic remove claims, never approve them.
- **Template reports only.** Always grounded, but terse. The template stays as the floor; an LLM
  may only improve on it.

## Consequences

- Nothing a model writes reaches a reviewer without passing the deterministic checks, and every
  claim links to its evidence in the console. Groundedness results are in
  [the evaluation](../evaluation.md).
- The checks do not judge meaning. A claim can cite real evidence and still mislead; the critic
  and the human review are the defences there.
- The number check is strict, so a model that writes a figure absent from its cited evidence (a
  total it worked out, say) is repaired or replaced by the draft.
