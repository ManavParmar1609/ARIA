# 0017. Keep an append-only, hash-chained decision record

## Status

Accepted. Extends [0008](0008-keep-runs-checkpoints-and-memory-in-one-sql-database.md).

## Context

ARIA stored every decision with its run: the review in the report row and the feedback table,
each message's outcome in the actions table, each blind check in the feedback table, and each
recalibration in the model file's metadata. Those rows are ordinary rows. Anyone who can write to
the database can change a reviewer's name, a decision or a severity after the fact, and nothing
would show it. Deleting a run removed its decisions with it, so a purge or a `DELETE` left no
trace of what had been decided or who deleted it.

The [EU AI Act reading](../eu-ai-act.md) listed a tamper-evident decision record as a gap, and
the engine hardening research asked for an immutable record per run (its item 17). Both want
the same thing: a record that shows when it has been changed, that outlives the runs it
describes, and that an auditor can check without trusting whoever runs the database.

## Decision

**One table, `decision_record`, that only grows** ([`models.py`](../../src/aria/db/models.py),
[`record.py`](../../src/aria/db/record.py)). Each entry holds a sequence number, a time, a kind
(review, edit, publish, send, blind check, recalibration, model swap, purge, deletion), the run
it concerns when there is one, who decided (a reviewer's display name, `cli` for the operator,
`system` for ARIA's own jobs: never a key), the decision's facts, the previous entry's hash and
its own SHA-256 over a canonical JSON of every other field. The first entry chains to a fixed
genesis hash.

**Append-only by construction and by the database.** The module offers `append`, `list_entries`
and `verify`, nothing else. The migration installs triggers that refuse `UPDATE` and `DELETE`
on SQLite and on SQL Server, and `create_all` installs the same ones for tests. Nothing links
the table to `runs`, so a deleted or purged run leaves its entries in place, and the deletion or
purge adds an entry of its own.

**One chain, however many writers.** The sequence number is the primary key, chosen by the
writer from the tail it read. Two writers that read the same tail cannot both insert the next
entry: the loser's insert fails on the key, and it reads the new tail and tries again, as the
run event log already does. There is no lock to hold across processes.

**Written at every decision, loudly or not at all.** The publish and reject steps, the resend,
the blind-check route, the two recalibration paths, the engine's model swap, the retention purge
and the delete route all append their entry right after the decision's own row. An entry that
cannot be written raises after an error-level log line: a graph step fails its run with the
reason, a route answers with an error, a job logs the failure. No path drops a record quietly.

**Facts, redacted, never log lines.** A payload holds what was decided (levels, decision,
action ids, versions, counts, a reviewer's comment or note cut to 500 characters), run through
the same redactor as everything else, with the run's own pseudonyms where it has a run. The
report's text, a message's body and the log lines stay in their own rows.

**Checked from three places.** `aria audit verify` and `GET /api/v1/audit/verify` walk the whole
chain and name the first entry that does not hold; `GET /api/v1/runs/{id}/record` lists one
run's entries; the console shows them on the incident page and the verdict in Settings.

## Alternatives considered

- **A column of hashes on the existing tables.** It would not catch a deleted row, could not
  outlive a purged run, and would spread the rule over six tables.
- **Signing each entry with a key.** A signature proves who wrote an entry only if the key is
  kept away from the database and the API process, which the same person usually runs. A chain
  needs no key, and anchoring its newest hash elsewhere gives the same protection against a
  rewritten history.
- **An external audit service or a ledger database.** Right for a deployment that already has
  one; too much for ARIA's default of one SQLite file or one Azure SQL database. The record is
  plain rows that any such service can ingest.
- **Recording in the same transaction as each decision.** It would make a chain conflict roll
  back the decision too. Writing the entry right after the decision's own row, and failing
  loudly when that fails, keeps each write small and keeps the mechanism one function.

## Consequences

- Changing, removing or reordering any entry breaks every hash after it, and the verifier names
  the first break. A chain that was rewritten end to end, by whoever administers the database,
  verifies: the record shows tampering, it does not prevent it. Keeping the newest hash somewhere
  that person cannot reach (the verify output prints it) catches that too.
- A step that runs twice after a database error writes its entry twice. Duplicates read as
  what they are, two attempts, and never as a changed decision.
- The record grows by a handful of rows per reviewed run and one per purged run, and is never
  purged itself. A deployment that must forget a person's name rewrites it under the
  administrator's own authority, which the chain will show.
- Reviews from A2A and AG-UI go through the same graph steps, so they are recorded the same way.
