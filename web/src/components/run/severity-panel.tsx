"use client";

import { LevelChip, SeverityBadge, SeverityScale } from "@/components/aria/severity";
import { decisionPhrase } from "@/lib/decision";
import { SEVERITIES, type SeverityAssessment } from "@/lib/api/types";
import { percent } from "@/lib/format";
import { LEVEL_RESPONSE } from "@/lib/levels";
import { cn } from "@/lib/utils";

import { Citations } from "./evidence";

/**
 * How serious: the level, what it means and what teams usually do, then the short list of levels
 * it could be and what that list promises. Scores, rules and the model sit under a closed
 * "How ARIA decided" (item 16).
 */
export function SeverityPanel({
  assessment,
  shortListHeld,
}: {
  assessment: SeverityAssessment;
  /** How often lists like this held the right level on the published test incidents. */
  shortListHeld?: number | null;
}) {
  const coverage = Math.round((1 - assessment.alpha) * 100);
  // A window unlike the ones the model learned from (or no model loaded): the probabilities are
  // normalised rule scores, so nothing here may read them as a calibrated confidence.
  const rulesOnly = assessment.model_version.startsWith("rules-only");
  // A floor that lifts the severity above what the model believed: say so plainly, with the
  // model's own view, instead of quoting a near-zero confidence for the class the floor chose.
  const floorHit = assessment.rule_hits.find(
    (h) => h.effect === "floor" && h.severity === assessment.floor,
  );
  const modelTop = SEVERITIES.reduce((best, s) =>
    (assessment.probabilities[s] ?? 0) > (assessment.probabilities[best] ?? 0) ? s : best,
  );
  const lifted =
    assessment.decided_by === "rules" && floorHit && modelTop !== assessment.severity
      ? floorHit
      : null;
  const how = lifted
    ? `Set by a safety rule: “${lifted.title}” keeps it at ${assessment.floor} or worse.`
    : decisionPhrase(assessment);
  const maxScore = Math.max(1, ...SEVERITIES.map((s) => assessment.rule_scores[s] ?? 0));
  return (
    // overflow-clip: the stamp starts large, and a transform still counts as overflow; clipped to
    // the card, it can never make a narrow screen scroll sideways.
    <section
      aria-labelledby="severity-title"
      className="grid min-w-0 gap-4 overflow-clip rounded-lg bg-raised p-5"
    >
      <h2 id="severity-title" className="text-base font-medium">
        How serious
      </h2>
      <div className="grid gap-2">
        {/* Keyed by level, so a reviewer's correction lands with its own stamp. */}
        <LevelChip
          key={assessment.severity}
          severity={assessment.severity}
          stamp
          className="justify-self-start"
        />
        <p className="text-sm">{LEVEL_RESPONSE[assessment.severity]}</p>
      </div>
      <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
        Short list:
        {assessment.prediction_set.length ? (
          assessment.prediction_set.map((s) => <SeverityBadge key={s} severity={s} size="sm" />)
        ) : (
          <span className="font-normal text-muted-foreground">no level was likely enough</span>
        )}
      </p>
      {/* What the short list means, in view: how often such lists held the right level, which is
          not how sure ARIA is of its first choice (item 16). */}
      <p className="-mt-2 text-sm text-muted-foreground">
        {rulesOnly
          ? "The calibrated model was not used for this window, so the short list comes from the rules alone."
          : `${
              shortListHeld != null
                ? `Short lists like this held the right level in ${Math.round(shortListHeld * 100)} of 100 past test incidents.`
                : `Short lists like this are built to hold the right level ${coverage} times in 100.`
            } That is how often the list was right, not ARIA's confidence in its first choice.`}
      </p>

      <details className="group grid gap-3 text-sm">
        <summary className="w-fit cursor-pointer font-medium text-muted-foreground hover:text-heading">
          How ARIA decided
        </summary>
        <div className="grid gap-4 pt-3">
          <p className="leading-relaxed">
            {how}{" "}
            <span className="text-muted-foreground">
              {lifted
                ? rulesOnly
                  ? `On their own, the rule scores put ${percent(assessment.probabilities[modelTop] ?? 0)} on ${modelTop}; the floor is there for cases the scores miss.`
                  : `On its own, the model put ${percent(assessment.probabilities[modelTop] ?? 0)} on ${modelTop}; the floor is there for cases the model has not learned.`
                : rulesOnly
                  ? "The bars are rule scores, not a calibrated confidence."
                  : assessment.set_empty
                    ? `No level is likely enough for the ${coverage}% short list on its own; ${assessment.severity} is the most likely, at ${percent(assessment.confidence)}.`
                    : `The model gives ${assessment.severity} ${percent(assessment.confidence)}.`}
              {assessment.auditable
                ? ` No language model was involved, so the decision can be checked from ${rulesOnly ? "the rules" : "the rules and the model"} alone.`
                : ""}
            </span>
          </p>
          <SeverityScale
            probabilities={assessment.probabilities}
            predictionSet={assessment.prediction_set}
            decided={assessment.severity}
            floor={assessment.floor}
            alpha={assessment.alpha}
            setEmpty={assessment.set_empty ?? false}
            rulesOnly={rulesOnly}
            drawBracket
          />
          {assessment.rule_hits.length > 0 ? (
            <div className="grid gap-2">
              <p className="font-medium">
                {assessment.rule_hits.length} {assessment.rule_hits.length === 1 ? "rule" : "rules"}{" "}
                matched; on their own they suggest {assessment.rule_severity}
              </p>
              <ul className="grid gap-2">
                {assessment.rule_hits.map((hit) => (
                  <li key={hit.rule_id} className="grid gap-0.5 border-l-2 border-rule pl-3">
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span>{hit.title}</span>
                      <span
                        className={cn(
                          "rounded-xs border px-1 text-xs",
                          hit.effect === "floor"
                            ? "border-sev1-fg/60 text-sev1-fg"
                            : "border-control text-muted-foreground",
                        )}
                      >
                        {hit.effect === "floor"
                          ? `keeps it at ${hit.severity} or worse`
                          : `+${hit.weight} to ${hit.severity}`}
                      </span>
                      <Citations ids={hit.evidence_ids} />
                    </p>
                    {hit.detail ? (
                      <p className="font-mono text-xs text-muted-foreground">{hit.detail}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
              <div className="grid grid-cols-4 gap-1.5 pt-1" aria-label="Rule score per level">
                {SEVERITIES.map((s) => (
                  <div key={s} className="grid gap-1">
                    <div className="h-1.5 rounded-full bg-sunken">
                      <div
                        className="h-1.5 rounded-full bg-control"
                        style={{
                          width: `${((assessment.rule_scores[s] ?? 0) / maxScore) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="tabular text-xs text-muted-foreground">
                      {s} {(assessment.rule_scores[s] ?? 0).toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground">No severity rule matched this window.</p>
          )}
          <p className="text-xs text-faint">
            {rulesOnly
              ? `Rules ${assessment.model_version.slice("rules-only:".length)}, model not used`
              : `Model ${assessment.model_version}`}
          </p>
        </div>
      </details>
    </section>
  );
}
