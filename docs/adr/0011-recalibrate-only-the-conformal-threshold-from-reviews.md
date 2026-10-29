# 0011. Recalibrate only the conformal threshold from human reviews

## Status

Accepted.

## Context

The conformal guarantee holds only on data like the calibration split, and ARIA was calibrated on
semi-synthetic windows ([0003](0003-severity-ground-truth-from-tags-and-a-written-policy.md)). A
deployment's own incidents differ. Reviewers settle the true severity of every run they approve
or edit, which is exactly the data a recalibration needs. Retraining the whole model on a trickle
of reviews, though, would let a handful of decisions reorder every class, and reviews arrive in
whichever process handles them.

## Decision

[`recalibration.py`](../../src/aria/severity/recalibration.py) implements the loop:

- **Record what the model saw.** Each human review stores the run's model input (`model_row`), the
  model version and the severity the reviewer settled on
  ([`workflow.py`](../../src/aria/graph/workflow.py)). An approval confirms ARIA's severity, an
  edit corrects it, and a rejection settles nothing and is left out. Automatic approvals on
  unattended runs are not recorded as reviews.
- **Move only the threshold.** Once `recalibrate_after` new reviews (30 by default, at least 10)
  have gathered since the loaded model was calibrated, ARIA recomputes the split-conformal
  threshold on all reviewed incidents. Coefficients and temperature stay as trained, so
  recalibration can widen or narrow prediction sets (and with them how often ARIA asks for
  review), but cannot change which class the model ranks first.
- **Version it and keep history.** The new model's version is `<trained version>-recal<n>`. It
  records `trained_version`, `recalibrated_from`, `n_reviewed` and coverage before and after, and
  is written atomically: a staging file, then a rename. The previous version stays beside it as
  `<stem>.<version>.json`.
- **Write to the shared models directory.** Recalibrations go to `ARIA_MODELS_DIR`, a volume the
  API and worker containers share, never over the trained model baked into the image. Readers use
  the live file when it exists and the trained one until then
  ([`model.py`](../../src/aria/severity/model.py), `live_model_path`).
- **Reload without a restart.** A severity engine checks the model file's modification time before
  each assessment and reloads it when it changed ([`engine.py`](../../src/aria/severity/engine.py)).
- **Count against the file.** New reviews are counted against the model file's own record, not
  the `used` marks in the database, so a model restored from an older file recalibrates again
  from the shared database.
- **Run it as a job or by hand.** The background job checks every `recalibrate_check_s` seconds
  (600 by default; see [0013](0013-run-background-jobs-where-runs-execute.md)), and
  `aria train recalibrate [--min-new-reviews N] [--dry-run]` runs it by hand.
  `GET /api/v1/feedback` and the console's settings page show where calibration stands.

## Alternatives considered

- **Retrain on reviews.** Needs far more labelled incidents than reviews provide early on, and
  changes rankings in ways a reviewer cannot predict.
- **Refit the temperature as well.** It moves every probability, and with them the auto-decide
  gate, on small samples.
- **Never recalibrate.** Leaves the guarantee resting on synthetic data.

## Consequences

- The guarantee is only as good as the reviews. Approvals count as confirmations, so
  rubber-stamped approvals make the sets look better calibrated than they are.
- Nothing happens below 10 reviews: at `alpha` 0.1 the conformal quantile is not finite on fewer.
- In `external` mode each worker recalibrates its own copy of the model file from the same
  reviews. The API process does not run the job, so the calibration that `/api/v1/feedback`
  reports comes from the API's own copy, which stays as trained unless both read the same file.
