# Validation log

Every change to the severity rules, the lexicon, the window features or their thresholds is
chosen on **validation seeds 51–56 only**: ring A (fresh windows of the familiar systems) and
ring B (every system held out in turn, the model refitted without it). The published test seeds
(41 and 42) and the real-data and new-domain suites are never run, read or tuned on while a
change is being chosen ([ADR 0015](adr/0015-measure-in-three-rings-and-record-what-was-tuned.md),
[`config/eval_registry.yaml`](../config/eval_registry.yaml)).

The yardstick is a cost per window, `(4 × severe misses + 2 × other under-triage +
over-triage) / n`, where a severe miss is a true SEV1 or SEV2 rated SEV3 or SEV4. A candidate is
adopted only when its ring B cost is no higher than the current one **and** its ring A cost is no
higher. Every candidate is validated on its own; a bundle is adopted only when it passes as a
bundle and each part passes alone.

Every run is recorded here, adopted or not. The numbers in the fenced blocks are pasted from the
validation script's own output (`A` and `B` are the rings; the lines below them are ring B per
held-out system), never typed by hand. Nothing in this file is a published result: the published
numbers come from `make eval` and live in [evaluation.md](evaluation.md).

## 2026-11-01: closing the severity gaps of the research report

The harness refits ring A and every ring B fold from the cached training windows (training seeds
11–14, 21, 31–32, at 6 windows per failure mode and 3 quiet windows per system) and scores the
384 validation windows (seeds 51–56, 2 per failure mode and 2 quiet per system) with the real
engine and policy, offline.

### Baseline: rules 2026.11.2, lexicon 2.1

Reproduced from the unchanged code before any change. It matches the baseline the previous wave
recorded in the same harness.

```text
base 82s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
     android {"acc": 0.75, "miss": 0, "severe": 0, "over": 0.25}
     apache {"acc": 0.917, "miss": 0, "severe": 2, "over": 0.083}
     bgl {"acc": 0.556, "miss": 0, "severe": 50, "over": 0.431}
     hadoop {"acc": 1.0, "miss": 0, "severe": 12, "over": 0.0}
     hdfs {"acc": 0.542, "miss": 1, "severe": 1, "over": 0.0}
     hpc {"acc": 0.604, "miss": 0, "severe": 28, "over": 0.208}
     linux {"acc": 0.667, "miss": 0, "severe": 4, "over": 0.333}
     mac {"acc": 0.5, "miss": 0, "severe": 0, "over": 0.5}
     openssh {"acc": 0.792, "miss": 0, "severe": 7, "over": 0.125}
     openstack {"acc": 1.0, "miss": 0, "severe": 0, "over": 0.0}
     proxifier {"acc": 0.792, "miss": 0, "severe": 0, "over": 0.208}
     zookeeper {"acc": 0.444, "miss": 1, "severe": 12, "over": 0.333}
```

### feat: the feature layer and lexicon 2.2, with the unchanged rules

What changed: a line with no level counts as an issue line only when the window has no levels at
all or also logs errors (before, always); each keyword category is also counted as distinct
patterns and as its share of the issue lines; `issue_events` and the issue lines' templates are
recorded; lexicon 2.2 adds the `cancellation` category, which also gives the model one more
feature. Why: the report's three count problems (unlevelled lines read as trouble, repeated lines
read as many, cancellations read as errors) and the review note on dismissed patterns all need
these signals.

The caches were rebuilt from the new code and the unchanged rules refitted on them. No
validation window has an unlevelled line (the parser derives a level for every line it reads, so
the corroboration rule cannot be told apart from today's behaviour there; it was chosen for the
OpenTelemetry convention it follows, not by these numbers), none has a cancellation, and the
model's new feature is zero on every training window, so both rings are unchanged. **Adopted.**

```text
feat 67s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
     android {"acc": 0.75, "miss": 0, "severe": 0, "over": 0.25}
     apache {"acc": 0.917, "miss": 0, "severe": 2, "over": 0.083}
     bgl {"acc": 0.556, "miss": 0, "severe": 50, "over": 0.431}
     hadoop {"acc": 1.0, "miss": 0, "severe": 12, "over": 0.0}
     hdfs {"acc": 0.542, "miss": 1, "severe": 1, "over": 0.0}
     hpc {"acc": 0.604, "miss": 0, "severe": 28, "over": 0.208}
     linux {"acc": 0.667, "miss": 0, "severe": 4, "over": 0.333}
     mac {"acc": 0.5, "miss": 0, "severe": 0, "over": 0.5}
     openssh {"acc": 0.792, "miss": 0, "severe": 7, "over": 0.125}
     openstack {"acc": 1.0, "miss": 0, "severe": 0, "over": 0.0}
     proxifier {"acc": 0.792, "miss": 0, "severe": 0, "over": 0.208}
     zookeeper {"acc": 0.444, "miss": 1, "severe": 12, "over": 0.333}
```

### c2a: a noise rule for windows made mostly of cancellations

What changed: a SEV4 scoring rule, `mostly_cancellations` (weight 2.0), when at least half of a
window's issue lines are client cancellations and there are at least five issue lines. Why:
OpenTelemetry records client cancellations at DEBUG, so a window made of them is not an error
storm. No validation window has a cancellation, so the rule never fires there and both rings are
unchanged; it rests on the convention and on unit tests. **Adopted.**

```text
c2a 144s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
```

### c2b: error counts by node and by critical component leave cancellation-heavy windows out

What changed: `errors_spread` and `critical_component_errors` require that cancellations are less
than half of the issue lines. The rules that need a spike (`error_storm`, `sustained_burst`) are
left as they are, because a spike of cancellations is a client giving up on a slow service. Same
reasoning and same outcome as c2a: unchanged on both rings. **Adopted.**

```text
c2b 191s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
```

### c2: c2a and c2b together

The cancellation discount as a bundle. Unchanged on both rings, as each part was. **Adopted.**

```text
c2 200s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
```

### Where one repeated pattern drives a keyword rule

Before choosing the pattern candidates, the validation windows were counted by how many distinct
patterns stood behind each keyword rule when it fired, and what the truth was. Where a rule fired
on a single pattern, the truth was mostly a real incident for `unavailability_reported` (ZooKeeper
quorum loss, HPC components unavailable, Hadoop's resource manager unreachable, BGL's ciod link
failures), `storage_failures` and `hardware_failure_widespread`, so a pattern threshold there
would cause severe misses and none was tried. It was always a quiet window for
`security_attempts` and `attack_widespread` (OpenSSH's background of failed logins is one
pattern; its attacks show three or more), and mixed for `unavailability_widespread` (quiet HPC
windows against its real outages) and for the network branch of `degradation_signs` (quiet HDFS
and macOS windows against HDFS block-serving exceptions and BGL tree-network errors). Those four
were tried, one at a time.

### c3a: repeated authentication failures need more than one kind of message

What changed: `security_attempts` (SEV3) also requires `keyword_templates.security >= 2`. Why:
the quiet OpenSSH windows fire it on one repeated pattern. Both rings' costs are unchanged (the
prediction sets moved by a hair). Passes the criterion. **Adopted.**

```text
c3a 93s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.88, "size": 1.57, "review": 1.0, "cost": 0.4036}
```

### c3b: authentication attacks against many hosts need more than one kind of message

What changed: `attack_widespread` (SEV2) also requires `keyword_templates.security >= 2`. Why: as
c3a, the same quiet OpenSSH windows. Both rings unchanged. Passes the criterion. **Adopted.**

```text
c3b 164s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
```

### c3c: services unreachable from several nodes need more than one kind of message

What changed: `unavailability_widespread` (SEV2) also requires `keyword_templates.unavailable >=
2`. Why: quiet HPC windows fire it on one repeated pattern (HPC's background reports components
unavailable). Ring A's cost is unchanged; ring B's falls, with fewer windows under-triaged and no
new severe miss. Passes the criterion. **Adopted.**

```text
c3c 203s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.24, "review": 0.279, "cost": 0.1849}
  B {"acc": 0.693, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.076, "over": 0.232, "cover": 0.883, "size": 1.57, "review": 1.0, "cost": 0.3932}
```

### c3d: network messages need more than one kind before they count as degradation

What changed: the network branch of `degradation_signs` (SEV3) also requires
`keyword_templates.network >= 2`. Why: quiet HDFS and macOS windows fire it on one repeated
pattern. But so do HDFS's block-serving exceptions and BGL's tree-network errors, which are real:
the cost rises on both rings, with more over-triage and more under-triage. Fails the criterion.
**Not adopted**; the rule keeps its line count.

```text
c3d 144s
  A {"acc": 0.833, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.146, "cover": 0.951, "size": 1.24, "review": 0.281, "cost": 0.1875}
  B {"acc": 0.651, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.083, "over": 0.266, "cover": 0.836, "size": 1.55, "review": 1.0, "cost": 0.4427}
```

### c4: burn rates against the system's own baseline

What changed: two rules that read `error_ratio_vs_baseline`, the window's error ratio over the
median error ratio of the system's recent runs in the database: at fourteen times or more, with
at least twenty errors in at least a hundred lines, a SEV2 signal below the activation
(`error_burn_page`); at six times or more, with at least ten errors, a SEV3 signal
(`error_burn_ticket`). Why: the Google SRE workbook's multiwindow burn rates, which rate errors
against what is usual rather than by count. Offline windows have no history, so the feature is
absent and the rules never fire: both rings are unchanged, which is what the run had to show.
The thresholds are judgement, not measurement. **Adopted.**

```text
c4 152s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.23, "review": 0.276, "cost": 0.1849}
  B {"acc": 0.688, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.081, "over": 0.232, "cover": 0.878, "size": 1.56, "review": 1.0, "cost": 0.4036}
```

### final: rules 2026.11.3 as committed, with lexicon 2.2 and the new features

The adopted parts together (c2, c3a, c3b, c3c and c4, plus the rule titles that name node counts
as stand-ins for blast radius, which change no feature), validated as one bundle on the final
code. Ring A's cost is unchanged from the baseline and ring B's is lower than the baseline's and
than any single part's, with fewer windows under-triaged, no new severe miss and slightly wider
sets. **Adopted** as `config/severity_rules.yaml` version 2026.11.3.

Not tried, by design: a pattern threshold on `unavailability_reported`, `storage_failures` and
`hardware_failure_widespread` (real incidents fire them on one repeated pattern), any change
chosen by looking at the test seeds or at a real-data or new-domain suite, and any threshold for
the burn-rate or cancellation rules beyond the convention they follow, since no validation window
has a history or a cancellation.

```text
final 166s
  A {"acc": 0.836, "miss": 0, "severe": 116, "miss_ub": 0.025, "under": 0.021, "over": 0.143, "cover": 0.951, "size": 1.24, "review": 0.279, "cost": 0.1849}
  B {"acc": 0.698, "miss": 2, "severe": 116, "miss_ub": 0.053, "under": 0.073, "over": 0.229, "cover": 0.888, "size": 1.57, "review": 1.0, "cost": 0.3854}
     android {"acc": 0.75, "miss": 0, "severe": 0, "over": 0.25}
     apache {"acc": 0.917, "miss": 0, "severe": 2, "over": 0.083}
     bgl {"acc": 0.556, "miss": 0, "severe": 50, "over": 0.431}
     hadoop {"acc": 1.0, "miss": 0, "severe": 12, "over": 0.0}
     hdfs {"acc": 0.667, "miss": 1, "severe": 1, "over": 0.0}
     hpc {"acc": 0.604, "miss": 0, "severe": 28, "over": 0.208}
     linux {"acc": 0.708, "miss": 0, "severe": 4, "over": 0.292}
     mac {"acc": 0.5, "miss": 0, "severe": 0, "over": 0.5}
     openssh {"acc": 0.792, "miss": 0, "severe": 7, "over": 0.125}
     openstack {"acc": 1.0, "miss": 0, "severe": 0, "over": 0.0}
     proxifier {"acc": 0.792, "miss": 0, "severe": 0, "over": 0.208}
     zookeeper {"acc": 0.444, "miss": 1, "severe": 12, "over": 0.333}
```

## How to run the harness again

The scripts are a copy of the previous wave's (`val.py` rebuilds the caches of training and
validation windows from the code in the working directory; `rules_val.py LABEL RULES_YAML`
refits ring A and every ring B fold and prints both costs) kept outside the repository, run from
the repository root with `PYTHONPATH=src`, every provider key blank and the Loghub samples under
`data/raw/loghub-2k`. Rebuild the caches after any change to the parser, the features or the
lexicon; a rules-only change needs only `rules_val.py`.
