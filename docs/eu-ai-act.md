# ARIA and the EU AI Act

This is the project's own reading of where ARIA stands under the EU AI Act (Regulation (EU)
2024/1689), written down as Article 6(4) asks of a provider. It is not legal advice. A deployer in
the EU should have their counsel confirm it for their own use. The official text was read through
the [AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-6) and law-firm
briefings, listed under each point.

## What ARIA does, in the Act's terms

ARIA reads a system's logs and alerts, and proposes a severity, a cited report and drafts of
outbound messages. A person reviews every one of them before anything is sent:

- the review step is an interrupt in the workflow, and no path sends a message or a ticket
  before approval ([`workflow.py`](../src/aria/graph/workflow.py));
- severity is decided by rules, a calibrated model and a prediction set, and a language model may
  only choose inside that set ([ADR 0002](adr/0002-severity-cascade-with-conformal-sets.md));
- ARIA does not act on the systems it watches: its tools are read-only
  ([`mcp/server.py`](../src/aria/mcp/server.py)).

It does not profile people. Log lines can contain personal data, such as user names or IP
addresses, and ARIA pseudonymises them before any model sees them
([`security/`](../src/aria/security/)).

## Is ARIA a high-risk system?

**Annex III.** The use case that could apply is point 2, critical infrastructure: "AI systems
intended to be used as safety components in the management and operation of critical digital
infrastructure". An organisation that runs critical digital infrastructure could use ARIA there.

**Article 6(3).** An Annex III system is not high-risk when it does not pose a significant risk of
harm, and in particular does not materially influence the outcome of decision-making, because it
does one of the following
([Service Desk, Article 6](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-6);
[William Fry](https://www.williamfry.com/knowledge/is-your-annex-iii-ai-system-high-risk-definitely-maybe/)):

1. a narrow procedural task;
2. improves the result of a previously completed human activity;
3. detects decision-making patterns, or deviations from them, without replacing or influencing the
   human assessment without proper review;
4. a task preparatory to an assessment relevant to an Annex III use case.

The exception never applies to a system that profiles natural persons.

**Our assessment.** As shipped, ARIA performs a preparatory task (point 4): it prepares the
material for a person's assessment of an incident, and that person decides. No outcome reaches
the world before a reviewer approves it. ARIA does not profile people. We therefore read ARIA, as
shipped, as not high-risk under Article 6(3).

**What would change that.** The assessment holds only while a person reviews. It would not hold
if a deployer:

- turned review off and let ARIA's output act on infrastructure directly;
- used ARIA as a safety component that triggers protective actions without review.

Annex III point 2 obligations (risk management, logging, human oversight, accuracy, robustness)
could then apply from 2 December 2027, the date the AI Omnibus set for Annex III systems
([Addleshaw Goddard](https://www.addleshawgoddard.com/en/insights/insights-briefings/2026/technology/eu-ai-act-ai-omnibus-formally-adopted/);
[National Law Review](https://natlawreview.com/article/eu-digital-omnibus-ai-enters-force); dates
from law-firm briefings). A provider relying on Article 6(3) must document the assessment before
placing the system on the market, and register it under Article 49(2).

## How ARIA meets the obligations anyway

Even where they do not bind it, ARIA is built to the high-risk obligations a careful deployer
would want:

| Article | What it asks | Where ARIA does it |
|---|---|---|
| 12, 19 and 26(6): record-keeping | Automatic logs over the system's life, kept at least six months | Every run's events, checkpoints, evidence, review decisions and outbound actions are stored and can be forked from any checkpoint ([ADR 0008](adr/0008-keep-runs-checkpoints-and-memory-in-one-sql-database.md)). Runs are kept until someone deletes them, unless the deployer sets a retention period; a purge then deletes the runs past it ([ops runbook](ops-runbook.md#retention-and-purge)). |
| 14: human oversight | People can understand, monitor, override, and stay aware of automation bias (14(4)(b)) | The review interrupt; evidence beside every claim; a prediction set that says which levels ARIA cannot rule out; reasons a person should confirm; blind checks that measure the model without anchoring the reviewer ([ADR 0014](adr/0014-promise-coverage-per-level-and-send-unfamiliar-windows-to-a-person.md)) |
| 15: accuracy and robustness | Declared accuracy, resilience to errors and to attempts to alter use | Published results by ring (familiar systems, systems never seen, real data), each with intervals ([evaluation.md](evaluation.md)); per-level coverage promises; the injection guard and its benchmark results ([threat model](threat-model.md)) |
| 50: transparency | People told when they read AI-generated text | Every report records whether a model or a template wrote it, and each run records the providers it called |

## Gaps

- **Tenant isolation.** One deployment serves one organisation. Serving several would need a
  tenant identifier on every stored row, which is not built.
- **A tamper-evident decision record.** Decisions are stored with the run, but not yet in an
  append-only, hash-chained log. It needs a database change, which waits for the owner's
  approval.

Retention is no longer a gap. A deployer sets how long runs are kept (`retention.days`, off by
default, so nothing is deleted unless they set it), and `aria purge` or a periodic job deletes the
runs past that period with everything that belongs only to them
([ops runbook](ops-runbook.md#retention-and-purge)). Where Article 26(6) applies, set at least six
months.
