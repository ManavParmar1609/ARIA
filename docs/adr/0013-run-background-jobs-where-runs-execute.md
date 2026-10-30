# 0013. Run the scan and recalibration jobs where runs execute

## Status

Accepted.

## Context

Two jobs run on a timer: the periodic log scan, which opens runs for incidents no alert caught,
and recalibration from reviews ([0011](0011-recalibrate-only-the-conformal-threshold-from-reviews.md)).
ARIA executes runs in one of two modes ([`worker.py`](../../src/aria/api/worker.py)):

- `inprocess`, the default for `aria serve`: the API executes runs in background tasks;
- `external`, used by docker compose and the Azure deployment: the API only records runs, and
  `aria worker` processes claim them from the database.

A job in the wrong process would run twice, or open runs that no one executes.

## Decision

- [`start_background_jobs`](../../src/aria/api/jobs.py) starts the configured jobs in whichever
  process executes runs:
  - in `inprocess` mode, the API's lifespan, where the scan hands each new run straight to the
    in-process worker;
  - in `external` mode, the `aria worker` poll loop, where the scan's runs wait in the queue for a
    worker to claim them.
- **The scan** ([`scan.py`](../../src/aria/api/scan.py)) is off until `ARIA_SCAN_INTERVAL_S` and
  `ARIA_SCAN_SOURCES` (`system=path` pairs) are set.
  - Each interval it reads the whole lines appended to each file and keeps a rolling window of the
    latest `scan_window_lines`.
  - It parses the window with the production parser (redaction and the injection guard included)
    and opens a run with trigger `scan` when the burst score reaches `scan_min_burst_score`.
  - The first look at a file starts at its end (history is not an incident), and a file that
    shrinks is read from the top.
  - A finding clears the window, so one burst opens one run. A finding is skipped while a scan run
    on that system is still open, or started within the alert grouping window.
- **Recalibration** checks every `recalibrate_check_s` seconds (600 by default; 0 turns it off) and
  refreshes the process's severity engine after it saves a new model.
- Both jobs stop when the process stops. A failed iteration is logged and tried again at the next
  interval rather than ending the job.

## Alternatives considered

- **Always run the jobs in the API.** In `external` mode the API executes nothing, so scan runs
  could not be started in process, and every API replica would repeat the work.
- **A separate scheduler**, such as cron or a Container Apps job. One more component to deploy and
  secure, for two light loops that need the runner's services anyway.

## Consequences

- Each job runs once per process that executes runs. The Azure worker can scale to three replicas,
  and each runs both jobs:
  - recalibration is safe to repeat, because the same reviews give the same threshold;
  - scan sources belong on one process only. The open-run check narrows the race between two
    processes tailing the same file, but does not close it.
- In `external` mode the workers recalibrate, so the API checks the shared model file before it
  reports calibration (`GET /api/v1/feedback`), and its view follows theirs
  ([0011](0011-recalibrate-only-the-conformal-threshold-from-reviews.md)).
- The scan reads files local to its process, so log files must be mounted where the jobs run.
