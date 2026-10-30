# Data card

This card covers the data ARIA trains and evaluates on: where it comes from, how it becomes
labelled log windows, and what that means for the published results. It follows the spirit of
[Datasheets for Datasets](https://arxiv.org/abs/1803.09010) and
[Data Cards](https://arxiv.org/abs/2204.01075).

The short version: the first sections of [evaluation.md](evaluation.md) use **real data with
labels its owners gave it**:

- a Hadoop cluster's log, replayed window by window against the label Hadoop experts gave each
  storage block ([below](#real-logs-with-expert-labels));
- the whole BlueGene/L log, in contiguous windows labelled by its administrators' alert tags
  ([below](#contiguous-bgl-windows));
- 55 Hadoop jobs, each labelled healthy or with the failure injected into it;
- a ServiceNow service desk's tickets, with their final priorities and SLA outcomes;
- GitLab.com's public production incidents, with the service and root cause their responders
  labelled ([below](#gitlabcoms-production-incidents));
- six public prompt-injection benchmarks, and a benchmark of benign look-alikes.

The other numbers come from **semi-synthetic** incident windows. Their log lines are real lines
from the public Loghub samples, but ARIA's scenario builder composes them into incidents: it
chooses which lines appear, on which nodes and at what times. Those results show how ARIA
behaves on that distribution. They are not a measurement of accuracy on production incidents.

| | |
|---|---|
| Log lines | Real lines from the Loghub 2k samples: 2,000 lines from each of 16 systems |
| Training and evaluation windows | **Semi-synthetic**: real lines, synthetic composition, 13 systems |
| Real-data evaluation | **Real**: 104,815 HDFS lines and the experts' label for each of 7,940 blocks; the full BGL log (4,747,963 lines) and its alert tags; the container logs of 55 Hadoop jobs and their failure labels; 24,918 ServiceNow tickets; GitLab.com's public production incidents and their responders' labels; 2,654 public prompt-injection attacks and 339 benign look-alikes. Only the ticket model trains on any of it, on the oldest tickets |
| Labels | BGL windows: the sysadmin alert tags, through a written rubric. Other systems: a documented scenario policy |
| Splits | Separate scenario seeds per split; the held-out test seeds are used only by `make eval` |
| Ticket data | The UCI ServiceNow log, fetched from checksum-pinned copies when the UCI host cannot be reached. The ticket model trains on its oldest 70% of tickets |
| In git | The manifest, the download code, small fixtures and the trained severity and ticket models. Raw datasets are never committed |

## Sources

Every source is pinned in [`data/manifest.yaml`](../data/manifest.yaml), with its licence and
citation. `make data` (`aria data download`) fetches each one into `data/raw/<name>/` and checks
its integrity (see [What is in git](#what-is-in-git-and-what-is-not)).

| Manifest key | What it is | Used for | Status in this build |
|---|---|---|---|
| `loghub-2k` | The Loghub 2k samples ([logpai/loghub](https://github.com/logpai/loghub) at commit `dd61d095`): 2,000 structured lines from each of Android, Apache, BGL, Hadoop, HDFS, HealthApp, HPC, Linux, Mac, OpenSSH, OpenStack, Proxifier, Spark, Thunderbird, Windows and Zookeeper, with hand-labelled event templates. BGL and Thunderbird lines open with a sysadmin alert-tag field; in these samples only BGL's lines hold alerts. | The scenario builder (13 of the 16 systems), the parsing evaluation (all 16) and the test fixtures | Downloaded |
| `loghub2-corrected` | Corrected templates for 14 of the 2k samples from Loghub-2.0 (Jiang et al., ISSTA 2024), commit `ac4aad2e` | The parsing evaluation scores the same parse against these as well, joined by line id | Downloaded |
| `hdfs-100k` | The first 100,000 HDFS_v1 lines plus the later lines of the blocks they start, with expert block-level anomaly labels (Xu et al., SOSP 2009), from the loglizer repository at commit `ac67f972` | The real-log evaluation ([below](#real-logs-with-expert-labels)) and a small committed cut for tests and the console's real incident. `aria data ingest` also loads it. No model trains on it. | Downloaded |
| `loghub-bgl` | The full BlueGene/L log (4,747,963 lines over 215 days) with sysadmin alert tags (Oliner and Stearley, DSN 2007), Zenodo record [8196385](https://zenodo.org/records/8196385) | Contiguous, real BGL windows ([below](#contiguous-bgl-windows)); `aria data ingest` loads its first lines | When Zenodo cannot be reached, the gzipped log comes from a public mirror and must match the sha256 in the manifest |
| `loghub-hadoop` | The container logs of 55 Hadoop MapReduce jobs, each labelled normal or with its injected failure: machine down, network disconnection or disk full (Lin et al., ICSE-SEIP 2016), same Zenodo record | The failed-jobs evaluation: each job triaged end to end | Downloaded from a mirror: a public repository at a pinned commit |
| `uci-incidents` | The UCI "Incident management process enriched event log" (dataset 498): a ServiceNow audit trail of 141,712 events for 24,918 incidents, with anonymised categorical codes and no free text | The ticket priority and SLA-breach models and their evaluation, and the outcome statistics of similar tickets | Downloaded from a mirror: two public copies of UCI's zip, checked against the sha256 in the manifest (the same CSV is in nine more repositories) |
| `bipia`, `injecagent`, `cyberseceval-pi`, `tensor-trust`, `giskard-injections`, `jailbreak-llms` | Public prompt-injection benchmarks: BIPIA (Yi et al.), InjecAgent (Zhan et al.), CyberSecEval 2 (Meta), Tensor Trust (Toyer et al.), Giskard's collection and in-the-wild jailbreaks (Shen et al.), each at a pinned commit | Measuring the injection detector on attacks it was never tuned on | Downloaded |
| `notinject` | NotInject (Li, Liu et al.): benign sentences that use one, two or three words common in injections | Measuring the detector's over-defence | Downloaded |
| `gitlab-incidents` | GitLab.com's production incidents (public issues in gitlab-com/gl-infra/production, created before October 2026), with the responders' severity, service and root-cause labels | The incident-memory evaluation: similar past incidents from each later incident's title | Downloaded through the issues API. A live source: the download records its snapshot's sha256 and date, and issues edited later can make a fresh download differ |

### Licences and citations

The Loghub datasets ship under this licence:

> The datasets are freely available for research or academic work, subject to the following
> condition: For any usage or distribution of the loghub datasets, please refer to the loghub
> repository URL (https://github.com/logpai/loghub) and cite the following loghub paper where
> applicable.

The paper is J. Zhu, S. He, P. He, J. Liu and M. R. Lyu, "Loghub: A Large Collection of System
Log Datasets for AI-driven Log Analytics", ISSRE 2023. The full notice ships with the fixtures
in [`tests/fixtures/loghub/LICENSE`](../tests/fixtures/loghub/LICENSE). The manifest lists the
paper to cite for each derived source.

The UCI incident log is licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
(DOI [10.24432/C57S4H](https://doi.org/10.24432/C57S4H)). Cite C. Amaral, M. Fantinato,
H. Reijers and S. Peres, "Enhancing Completion Time Prediction Through Attribute Selection",
2018.

BIPIA, CyberSecEval 2 (its `CybersecurityBenchmarks` folder), NotInject, Giskard's collection
and the jailbreak prompts are MIT-licensed. InjecAgent and Tensor Trust state no licence in
their repositories; ARIA reads them only to evaluate the detector and never redistributes them.
The manifest lists the paper to cite for each.

GitLab.com's production incidents are public issues in
[gitlab-com/gl-infra/production](https://gitlab.com/gitlab-com/gl-infra/production/-/issues),
with no licence stated. ARIA reads them through GitLab's issues API only to evaluate incident
memory, keeps them under `data/raw/`, and never redistributes them.

ARIA's code is MIT-licensed, but the data terms still apply to everything derived from the data.
That includes the committed severity model and the seeded incident memory, which are built from
Loghub lines. Check the Loghub terms before any commercial use.

### Sources considered and not used

The search for real, labelled data covered public log, incident, ticket, postmortem and
prompt-injection collections. These were reachable but left out, or could not be reached:

| Source | Why it is not used |
|---|---|
| BPI Challenge 2014 (Rabobank ICT incidents) | Its priority is a fixed function of impact and urgency (every pair maps to one priority) and it has no SLA outcome, so it would only confirm the matrix the UCI log already measures |
| BPI Challenge 2013 (Volvo IT incidents) | Impact only, no priority, SLA or free text |
| OpenStack fault-injection runs (Cotroneo et al., ESEC/FSE 2019) and Nezha (Yu et al., ESEC/FSE 2023) | Reachable and labelled, but about 10 GB and 2 GB of logs; candidates for a future fault-localisation evaluation |
| Thunderbird sample (LogLead), splunk attack_data, OTRF Security-Datasets | Lines sampled out of order (no windows), or labels per dataset file rather than per line or window |
| GitHub, Google Cloud and AWS status-page archives; danluu and Kubernetes postmortem lists | Short public notices or link lists: too little text, or no labels ARIA can be scored against |
| Full Thunderbird, Spirit, Liberty, HDFS_v2, Loghub-2.0 full logs, RCAEval, MSDS, Eadro | Hosted only on Zenodo, figshare, Hugging Face, USENIX or similar hosts, which could not be reached when ARIA's datasets were gathered, and no verifiable copy was found elsewhere |

## What is in git, and what is not

In git:

- [`data/manifest.yaml`](../data/manifest.yaml): every source, with its pinned commit or record,
  licence and citation.
- [`src/aria/data/download.py`](../src/aria/data/download.py): the downloader and its integrity
  checks.
  - Git sources check out a pinned commit, so the commit hash is the checksum.
  - Zenodo files are checked against the md5 that the Zenodo record API publishes.
  - UCI and plain HTTP files are checked against a pinned sha256. Where none is pinned, the
    first download records one in `data/checksums.lock`, and every later download is checked
    against it.
  - Mirrors are trusted only by their own pinned sha256 or commit.
  - The GitLab.com incident tracker is a live API and cannot be pinned: the download records the
    snapshot's sha256 and date beside it instead.
- [`tests/fixtures/loghub/`](../tests/fixtures/loghub/): small subsets of the 2k samples for 13
  systems, with rows unmodified. For each system they keep every BGL alert line, up to 40 lines
  per failure mode and up to 120 background lines. They are rebuilt with
  [`scripts/make_fixtures.py`](../scripts/make_fixtures.py) and ship with the Loghub licence
  notice.
  - Tests use them.
  - Commands fall back to them when `data/raw/loghub-2k` is missing. Results computed on them
    say so in the report and fail the CI gate.
- [`tests/fixtures/real/hdfs/`](../tests/fixtures/real/hdfs/): a real cut of the HDFS sample,
  every line of one block in eight over ten minutes (9,914 lines, 873 blocks), with the experts'
  labels and the Loghub licence notice. Tests use it, and the console replays it as a real
  incident. It is rebuilt with
  [`scripts/make_real_fixtures.py`](../scripts/make_real_fixtures.py).
- [`models/severity_log.json`](../models/severity_log.json) and
  [`models/severity_log.report.json`](../models/severity_log.report.json): the trained severity
  model and its training report.
- [`models/severity_ticket.json`](../models/severity_ticket.json): the ticket priority and SLA
  models, trained on the oldest 70% of the UCI log's tickets. Its vocabulary is the log's
  anonymised codes. See the [model card](model-card.md).
- [`config/`](../config/): the failure-mode catalog, the labelling rubric, the severity rules,
  the keyword lexicon and the service catalog.
- [`runbooks/`](../runbooks/): 19 example runbooks written for this project. They supply the
  fixes that incident memory and reports cite. They are examples to adapt, not procedures
  validated anywhere.
- Results and recordings derived from the data:
  - [`docs/eval-results.json`](eval-results.json) and [`docs/eval-live.json`](eval-live.json):
    evaluation results.
  - `web/src/data/demo-run.json`: one recorded offline run on a semi-synthetic scenario.

Not in git (see [`.gitignore`](../.gitignore)):

- `data/raw/`, `data/processed/` and `data/cache/`: downloads and intermediate files.
- Local databases (`*.db`, `*.sqlite`): ingested datasets, runs and incident memory.
- `models/embed_local.npz`: the offline embedder, which `aria seed` fits on the incident corpus.

## Real logs with expert labels

`hdfs-100k` is loglizer's HDFS_100k sample of the log a Hadoop cluster of more than 200 Amazon
EC2 nodes wrote on 9 November 2008 (HDFS_v1 in Loghub): the log's first 100,000 lines, about 13
minutes, then the later lines of the blocks those lines started. No block starts after line
100,000, so the last stretch holds only those blocks. Hadoop experts labelled each storage block
Normal or Anomaly, from the whole 38-hour log (Xu et al., SOSP 2009). The real-log evaluation
([`src/aria/evals/real.py`](../src/aria/evals/real.py)) replays the lines offline in overlapping
windows through the production parser's lifecycle check, and compares ARIA's verdict on each
block with the experts'. It reports the result with and without the last stretch. It is not a
run of the deployed log scan, which opens runs on bursts of ERROR or FATAL lines; this log has
none.

- **Nothing is composed.** The lines are the cluster's own; the sample keeps every line of the
  blocks it holds, and the replay chooses only the windows.
- **Nothing trains on it.** The lifecycle check learns from each window as it reads it, without
  labels. The labels are used only to score the result and to describe the misses by their
  step counts. The check's settings were chosen on this log, with its labels in view.
- **What the labels mean.** A label says a block had a problem somewhere in the 38 hours, not
  how severe an incident it was, so this measures detection, not severity. Some labelled
  failures take exactly the step counts of common healthy blocks here; the report counts them.
- **Overlap.** A handful of these lines also appear in the Loghub HDFS 2k sample that the
  scenario builder draws on; the report gives the count.

## GitLab.com's production incidents

GitLab runs GitLab.com in the open: each production incident is a public issue, labelled by the
responders with the service that failed (`Service::`) and, after review, its root cause
(`RootCause::`). The download asks GitLab's issues API for every issue labelled `incident`
created before October 2026, with fixed parameters, and keeps each issue's title, description,
labels, state and dates. The evaluation
([`src/aria/evals/gitlab.py`](../src/aria/evals/gitlab.py)) puts the incidents opened before
2023 into ARIA's retrieval index, from their titles and descriptions, and asks for similar past
incidents from each later incident's title alone.

- **Nothing is composed and nothing trains on it.** The labels only score the results; they never
  enter the index or the queries.
- **What the labels mean.** A service or root-cause label says what the responders concluded,
  sometimes long after the incident. Labels that say the field is unknown (`Needed`,
  `Indeterminate`, `NotNeeded`) count as no label, and incidents without one are neither queries
  nor answers.
- **A live source.** Issues can be edited or relabelled after the download, so the download
  records its snapshot's sha256 and date, and [evaluation.md](evaluation.md) quotes them.

## How semi-synthetic windows are built

The Loghub 2k samples are 2,000 lines sampled from each system's log, so they hold no
contiguous incidents with timing. The scenario builder
([`src/aria/data/scenarios.py`](../src/aria/data/scenarios.py)) composes incident windows from
them:

1. It picks real lines.
2. It gives them new timestamps and assigns them to nodes.
3. It renders them as raw lines in the system's own format.

Every message is a real Loghub line. The timing, the node assignment and the mix of lines are
synthetic.

### Failure modes

[`config/scenarios.yaml`](../config/scenarios.yaml) defines 21 failure modes over 13 systems:

- 5 BGL modes, selected by alert tag;
- 13 modes on 10 other systems, selected by a regex on the message;
- 3 benign modes: error-level lines that need no action, there to measure over-triage.

| System | Failure modes | Lines selected by | Label source |
|---|---|---|---|
| BGL | Kernel panic, memory interrupts, Lustre mount failure, CIOD link failure, tree-network errors | Alert tags | Rubric |
| HPC | Interconnect link errors, component unavailable, power-supply failure | Message regex | Policy |
| Hadoop | ResourceManager unreachable, HDFS lease renewal | Message regex | Policy |
| ZooKeeper | Quorum connection loss; connections from old clients (benign) | Message regex | Policy |
| HDFS | DataNodes failing to serve blocks | Message regex | Policy |
| OpenSSH | Brute-force attempts | Message regex | Policy |
| Linux | Repeated authentication failures | Message regex | Policy |
| OpenStack | Image cache missing base files | Message regex | Policy |
| Apache | mod_jk workers in error state | Message regex | Policy |
| Proxifier | Clients cannot connect through the proxy | Message regex | Policy |
| Thunderbird | Name resolution failures | Message regex | Policy |
| Mac | Cocoa scripting errors (benign) | Message regex | Policy |
| Android | Task-permission warnings (benign) | Message regex | Policy |

### Line pools

Each failure mode draws from an incident pool. For BGL modes, the pool is the lines whose alert
tag is one of the mode's tags. For the other modes, it is the lines whose message matches the
mode's regex.

Each system also has a background pool: lines that match none of its failure modes, carry no
alert tag, and are DEBUG, INFO or unlevelled. Some modes rest on very few distinct source
lines:

| Failure mode | Lines in the incident pool | Distinct messages |
|---|---|---|
| `bgl.kernel_panic` | 9 | 4 |
| `bgl.memory_interrupts` | 90 | 2 |
| `bgl.lustre_mount_failure` | 11 | 11 |
| `bgl.ciod_link_failure` | 26 | 26 |
| `bgl.tree_network_errors` | 5 | 5 |
| `openssh.bruteforce` | 1,229 | 608 |
| `linux.auth_failures` | 536 | 51 |
| `zookeeper.quorum_connection_loss` | 1,219 | 10 |
| `hadoop.resourcemanager_unreachable` | 629 | 7 |
| `hadoop.hdfs_lease_renewal` | 326 | 326 |
| `hdfs.block_serve_exceptions` | 80 | 80 |
| `hpc.interconnect_link_errors` | 467 | 6 |
| `hpc.component_unavailable` | 12 | 12 |
| `hpc.psu_failure` | 5 | 2 |
| `openstack.image_cache_missing` | 30 | 1 |
| `apache.mod_jk_worker_error` | 551 | 17 |
| `proxifier.proxy_connectivity` | 66 | 36 |
| `thunderbird.dns_resolution` | 39 | 38 |
| `mac.cocoa_scripting_noise` | 91 | 83 |
| `android.permission_noise` | 192 | 11 |
| `zookeeper.old_client_noise` | 39 | 39 |

These counts come from the pinned samples. Reproduce them with:

```bash
uv run python -c "from pathlib import Path; from aria.data.scenarios import LinePools; p = LinePools.from_loghub(Path('data/raw/loghub-2k')); print({k: (len(v), len({r.message for r in v})) for k, v in p.incident.items()})"
```

### One window

`ScenarioBuilder.build` composes one window:

- **Background.** Background lines arrive throughout the window at a Poisson rate.
- **Incident lines.** They start after a quiet lead-in of a quarter of the window, rise to a
  peak and taper off (a triangular intensity).
- **Nodes.** Incident lines are spread over the chosen number of nodes. The builder uses real
  node names from the sample when it has enough, and otherwise names nodes
  `<system>-node-NNN`.
- **Quiet windows.** These hold background traffic only and are labelled SEV4.

### The benchmark suite

`ScenarioBuilder.suite` varies scope and rate for each failure mode:

- windows of 12, 20 or 30 minutes;
- 1, 2, 3, 5, 8, 12 or 30 affected nodes;
- 15 to 45 background lines a minute;
- incident rates of 3, 8, 20, 60 or 160 lines a minute.

Training and the full evaluation build 6 windows per failure mode and 3 quiet windows per
system for each seed. These are the defaults of `train_from_loghub` and `SIZES["full"]` in
[`src/aria/evals/run.py`](../src/aria/evals/run.py).

Two more properties hold for every window:

- **A shared history.** Features such as "novel template" need a history to compare against. A
  30-minute routine window, built from seed 9,999, stands in for the history a deployment
  accumulates, so these features mean the same in training as in a live run.
- **Reproducibility.** Every random choice comes from a seeded generator, so the same seed and
  samples always give the same windows.

Every scenario is marked `synthetic=True`. Seeded memory incidents are marked synthetic with
`source="curated"`. Their time to resolve is left empty, because the scenarios do not record
how long a fix took.

### Seeds and splits

Each split uses its own scenario seeds, so no window appears in two splits.

| Split | Seeds | Used for |
|---|---|---|
| Train | 11, 12, 13, 14 | Fitting the logistic regression (its C is chosen by cross-validation inside train) |
| Temperature | 21 | Temperature scaling |
| Conformal | 31, 32 | The conformal threshold |
| Test | 41, 42 | `make eval` only |
| Memory | 51, 52 | Seeded incident memory for retrieval (`aria seed` builds 3 windows per failure mode for each seed and leaves out quiet windows) |

Window counts and labels for the committed model (version `severity-log-20261029-a362d541`).
These come from its training report,
[`models/severity_log.report.json`](../models/severity_log.report.json):

| Split | Windows | SEV1 | SEV2 | SEV3 | SEV4 |
|---|---|---|---|---|---|
| Train | 660 | 68 | 157 | 187 | 248 |
| Temperature | 165 | 13 | 45 | 45 | 62 |
| Conformal | 330 | 33 | 84 | 92 | 121 |

The label distribution of the held-out test windows is in
[evaluation.md](evaluation.md#severity).

**The splits differ in composition, not in source lines.** Every split draws from the same
2k-line pools, so test windows reuse messages and templates that training saw. The test
measures generalisation to new scopes, rates, timings and mixes. It does not measure
generalisation to unseen log lines or unseen systems.

### Contiguous BGL windows

When the full BGL log is present, `aria data ingest` builds real windows from it:

1. It reads up to 500,000 lines of `BGL.log` (the default).
2. It cuts 10-minute tumbling windows that hold at least 5 events.
3. It labels each window with the same rubric.
4. It assigns time-ordered splits: the first 60% train, the next 20% calibration and the last
   20% test.

These windows are real, not synthetic (`synthetic: False`), and a run can triage one by its
`window_id`. No model trains on them.

The evaluation reads the whole log itself, independently of the database: contiguous 20-minute
windows (the training scenarios' middle length), each labelled by the same rubric and rated by
ARIA from its lines alone, with the alert tags replaced by `-` before parsing. Loghub's 2k BGL
sample was drawn from this log, so the evaluation reports how many lines carry a message that
also appears in the sample the scenarios are built from.

## Labels

ARIA uses four levels:

- SEV1: a widespread outage or data-loss risk;
- SEV2: major degradation or a failing critical component;
- SEV3: contained errors;
- SEV4: noise.

Each window records where its label came from as `label_source`.

### BGL windows: the alert-tag rubric

System administrators tagged BGL alert lines (Oliner and Stearley, DSN 2007); untagged lines
carry `-`. [`config/labeling/bgl_alert_impact.yaml`](../config/labeling/bgl_alert_impact.yaml)
maps each tag to an impact class:

- **Critical (7 tags):** kernel panics, machine checks, power faults, file-system shutdown and
  the control system going down.
- **Major (25 tags):** kernel terminations, memory and storage interrupts, mount failures, and
  network and link faults. Tags the file does not list also count as major.
- **Minor (9 tags):** recoverable control-daemon errors.

The rules below are checked from top to bottom, and the first that holds sets the window's
severity. In a scenario they read the tags of the injected incident lines.

| Severity | Any of |
|---|---|
| SEV1 | Critical tags on 4 or more nodes; 50 or more critical alerts; major tags on 64 or more nodes |
| SEV2 | At least 1 critical alert; major tags on 8 or more nodes; 100 or more major alerts |
| SEV3 | At least 1 major alert; 5 or more minor alerts |
| SEV4 | Everything else |

### Other systems: the scenario policy

Each non-BGL failure mode in [`config/scenarios.yaml`](../config/scenarios.yaml) has a base
severity and escalations. OpenSSH brute force, for example, is SEV3, rising to SEV2 on 6 or
more hosts and to SEV1 on 24 or more.

The builder applies these rules to the composition's true scope: the nodes that received
incident lines, and the peak number of incident lines per minute. Node-count escalations apply
only where the log format names the host. Hadoop, HDFS, Apache, Proxifier and Android lines do
not, so no label depends on information that a reader of the logs lacks. Benign modes and quiet
windows are SEV4.

These policies are the project's documented judgement, not dataset annotations, and the
results on them are reported as synthetic.

### Why the labels do not grade the rules against themselves

- **BGL.** The rubric reads alert tags. ARIA's rules
  ([`config/severity_rules.yaml`](../config/severity_rules.yaml)) and the model's features read
  only what the parser computes: message text, levels, timing, nodes and components, plus any
  firing alerts. The tag is the first field of a raw BGL line, but no feature reads it. Evidence
  shown to a model also carries the message, not the raw line with its tag.
- **Other systems.** Policy labels come from the catalog's per-mode severities and from the
  composition's true node count and rate, all fixed before any parsing. They are not computed
  from ARIA's features. They do depend on scope and rate, which ARIA's features estimate (for
  example error nodes and peak errors per minute). On these systems the benchmark therefore
  measures how well ARIA recovers a documented policy from the logs, not ground-truth business
  impact.
- **Quarantined lines.** Lines quarantined as possible prompt injection are excluded before any
  feature is computed.

## Preprocessing

`aria data ingest` stores dataset rows as published. Every line then passes through the parser
([`src/aria/parsing/parser.py`](../src/aria/parsing/parser.py)) before ARIA analyses it, shows
it to a model or stores it for tools. That holds in live runs, training, memory seeding and
evaluation alike; training and seeding use fixed keys, so their features are reproducible. In
order:

1. **Sanitise.** NUL bytes and terminal colour codes are dropped, and invalid characters are
   replaced.
2. **Cap.** Lines longer than 2,000 characters are truncated, and a run takes at most 20,000
   lines (`guardrails` in [`config/aria.yaml`](../config/aria.yaml)). Both caps are reported.
3. **Scan for prompt injection** ([`src/aria/security/injection.py`](../src/aria/security/injection.py)).
   A line that reads like an instruction to a model is quarantined:
   - it is kept out of template mining and features;
   - it is shown to reviewers with a flag;
   - it is never stored for tools;
   - it reaches a model only as fenced, quoted evidence.
4. **Redact** ([`src/aria/security/redaction.py`](../src/aria/security/redaction.py)).
   - These are replaced with `[REDACTED]`:
     - private keys (also one printed over many lines) and JWTs;
     - AWS, NVIDIA, OpenAI, Google, Stripe and SendGrid keys;
     - GitHub, GitLab and Slack tokens, Slack webhook paths, bearer tokens and Basic credentials;
     - credentials in URLs;
     - the value of any setting whose name holds a password, secret, token or key, as in
       `DB_PASSWORD=…`, `"api_key": "…"` or a connection string's `AccountKey=…`;
     - payment card numbers that pass the Luhn check.
   - E-mail and IP addresses are pseudonymised with a keyed hash, for example `ip-3fa2c1d0`.
     A pseudonym is the same everywhere within a run. Each run uses a fresh key, so pseudonyms
     cannot be linked across runs.
5. **Parse.** The parser applies the per-system line formats from the Loghub benchmark settings,
   normalises levels and mines templates with Drain. Lines from other systems use a generic
   format (ISO timestamp, level, component, message).

Hostnames, node names, usernames and component names are not redacted, because triage needs
them. The [threat model](threat-model.md) covers what these controls do and do not stop.

## Known biases and gaps

- **Repetition.** All splits share one pool of a few thousand lines, and some failure modes rest
  on one to five distinct messages (see [line pools](#line-pools)). Templates repeat across
  windows far more than in a real fleet, which flatters every method that reads text.
- **Stylised incidents.** Each window holds one failure mode with a clean onset, a triangular
  burst and Poisson background. Real incidents overlap, cascade and drift.
- **A clean background.** Background lines are DEBUG, INFO or unlevelled, so outside the benign
  modes, error-level lines belong to the incident. Real fleets also log routine errors.
- **Policy labels.** They encode this project's judgement, and they track scope and rate
  closely.
- **The raw-text baseline.** Raw BGL lines carry the alert tag as their first field, as in the
  public dataset. The TF-IDF baseline in [evaluation.md](evaluation.md#severity) strips that
  field before it reads a window's text, and ARIA's features never read it, so neither sees the
  tags that define the BGL labels. The baseline's tokens are words of three or more letters, so
  it cannot count hosts, which the policy labels depend on.
- **Coverage.**
  - The scenarios cover 13 systems; HealthApp, Spark and Windows appear only in the parsing
    evaluation.
  - All the logs are in English.
  - Timestamps are synthetic, starting from 2026-03-02 UTC, with no daily or weekly patterns.
- **One company's tickets.** The UCI log's fields are anonymised codes with no free text, from
  one service desk over one year. ARIA never links it to Loghub, and fixes come from the
  project's runbooks instead.
- **One company's incidents.** GitLab.com's incidents come from one SaaS platform's own
  responders, in their own vocabulary, and their titles are often written before the cause is
  known. Its labels name GitLab's services, not the systems the log scenarios cover.
- **Mirrors.** Where a source's home host is blocked (Zenodo, UCI), the copy comes from a public
  repository. A file copy must match the sha256 pinned in the manifest; a repository copy is
  pinned to a commit. The BGL and UCI copies were also compared with independent copies, but
  none could be compared with the original host.
- **The project wrote the injection corpus.** Both the prompt-injection corpus
  ([`src/aria/evals/edge.py`](../src/aria/evals/edge.py)) and the detector are this project's
  own work, and the detector was tuned on that corpus. Read the
  [edge-case results](evaluation.md#edge-cases-and-prompt-injection) as an upper bound, and the
  [public benchmarks](evaluation.md#prompt-injection-public-benchmarks), which it was never
  tuned on, as the independent measure.

## Intended uses

- Training, calibrating and evaluating ARIA's severity model, and comparing it with simple
  baselines under the same conditions.
- Seeding incident memory, so that retrieval, reports and demos have a labelled history to work
  from.
- Tests, the offline demo and the recorded run on the landing page.

## Out of scope

- Claims about accuracy on production incidents, or on systems and log formats that are not in
  the catalog.
- Treating the policy labels as ground truth about business impact, or comparing other products
  on these windows as though they were real incidents.
- Any use the Loghub or UCI licences do not allow.

## Maintenance

- **Updating a source.** Change its pin in the manifest, then download, ingest, retrain and
  evaluate again. Regenerate the fixtures with `uv run python scripts/make_fixtures.py`.
- **Changing labels.** The rubric and the scenario policies live in `config/`. Changing either
  changes the labels, so retrain the model and regenerate the evaluation afterwards.
- **Problems.** Report data issues on the repository's issue tracker.

To rebuild everything from the sources:

```bash
make data
```

```bash
make seed
```

```bash
make train
```

```bash
make eval
```

These four commands do the following:

- `make data` downloads and verifies every source in the manifest.
- `make seed` migrates the database, ingests the downloaded datasets, loads the runbooks, seeds
  incident memory and fits the offline embedder.
- `make train` fits the severity model and the ticket models. The severity model needs the
  Loghub samples: without them, training stops rather than replace the committed model with one
  fit on the test fixtures (`aria train severity --fixtures` does that on purpose). The ticket
  models read the ingested UCI log, or the downloaded file when nothing is ingested, and are
  skipped when neither is there.
- `make eval` runs every suite and regenerates [evaluation.md](evaluation.md).

See also: the [model card](model-card.md), the [threat model](threat-model.md), the
[ops runbook](ops-runbook.md), the [architecture decisions](adr/README.md) and the
[README](../README.md).
