# 0012. The content-safety check is optional and fails closed

## Status

Accepted. Off by default (`guardrails.safety_model: false` in
[`aria.yaml`](../../config/aria.yaml)).

## Context

ARIA already confines what models write. Severity can only come from the prediction set
([0002](0002-severity-cascade-with-conformal-sets.md)), report text must pass the deterministic
grounding checks ([0007](0007-every-report-claim-cites-evidence.md)), and comms drafts must pass
their audience's rules. None of those checks judges whether text is harmful, such as a draft that
tells responders to do something dangerous, or abusive wording. The brief asked for NVIDIA's open
Nemotron content-safety models as an optional guardrail.

## Decision

- When `guardrails.safety_model` is on, a safety model reads LLM-written text before ARIA uses it
  ([`safety.py`](../../src/aria/security/safety.py)): the report's claims after the LLM narrative,
  and each LLM-polished comms draft.
- The text goes to the `safety` provider chain as the assistant turn after a one-line description
  of the task. ARIA reads NemoGuard-style JSON verdicts (`"Response Safety": "unsafe"`, with
  categories) and plain `safe` or `unsafe` answers.
- **It fails closed.** An unreadable verdict, no configured safety model, a spent budget or a
  provider error all count as flagged.
- A flagged report falls back to the grounded deterministic draft, and a flagged comms draft is
  dropped for the deterministic one. The report's metadata records whether the check passed,
  flagged the text or was skipped.

## Alternatives considered

- **Fail open when the safety model is down.** It keeps the LLM's wording during an outage, but a
  guardrail that vanishes under load or attack protects nothing.
- **Azure AI Content Safety or Prompt Shields.** The brief allows them when configured. They have
  their own APIs rather than chat completions and are not integrated.
- **On by default.** It adds a model call per report and per draft, and the default model ID is
  not yet verified.

## Consequences

- Turning the check on can only make output more conservative. In the worst case every run
  publishes the deterministic draft and deterministic comms.
- The default model ID, `nvidia/nemotron-3.5-content-safety`, is in NIM's model catalog (checked
  2026-10-29), but ARIA has not called it live, so its verdict format is unverified.
  `aria providers check` reports whether the configured safety model is in the catalog; send it
  a few known-safe and known-unsafe texts before turning the check on.
- Screening log lines for prompt injection is a separate control in the parser, on by default.
  This check is about what models write, not what they read.
