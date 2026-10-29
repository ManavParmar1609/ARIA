"use client";

import { ChevronDownIcon } from "lucide-react";
import { AnimatePresence, useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";

import { SeverityBadge, SeverityScale } from "@/components/aria/severity";
import { Button } from "@/components/ui/button";
import { SEVERITIES, SEVERITY_MEANING, type SeverityAssessment } from "@/lib/api/types";
import { percent } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Citations } from "./evidence";

const HOW: Record<string, string> = {
  rules: "Rules decided it: a safety floor fixed it, or the rules agreed with a confident model.",
  model: "The calibrated model decided it: its prediction set held a single class.",
  llm: "The LLM chose it from inside the model's prediction set.",
  fallback:
    "ARIA was not sure enough to decide alone, so it took the most severe class in the prediction set and asked for review.",
  human: "A reviewer set it.",
};

/** Severity and why: the instrument, the decision path and the rule trace. */
export function SeverityPanel({ assessment }: { assessment: SeverityAssessment }) {
  const [traceOpen, setTraceOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const coverage = Math.round((1 - assessment.alpha) * 100);
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
    ? `A safety floor decided it: “${lifted.title}” holds it at ${assessment.floor} or above.`
    : assessment.decided_by === "fallback" && assessment.set_empty
      ? "ARIA was not sure enough to decide alone, so it took the most likely class and asked for review."
      : (HOW[assessment.decided_by] ?? assessment.decided_by);
  const maxScore = Math.max(1, ...SEVERITIES.map((s) => assessment.rule_scores[s] ?? 0));
  return (
    // overflow-clip: the stamp starts large, and a transform still counts as overflow; clipped to
    // the card, it can never make a narrow screen scroll sideways.
    <section
      aria-labelledby="severity-title"
      className="grid min-w-0 gap-4 overflow-clip rounded-lg bg-raised p-4 sm:p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1">
          <h2 id="severity-title" className="eyebrow text-muted-foreground">
            Severity
          </h2>
          <p className="text-xs text-muted-foreground">{SEVERITY_MEANING[assessment.severity]}</p>
        </div>
        {/* Keyed by level, so a reviewer's correction lands with its own stamp. */}
        <SeverityBadge key={assessment.severity} severity={assessment.severity} stamp />
      </div>
      <SeverityScale
        probabilities={assessment.probabilities}
        predictionSet={assessment.prediction_set}
        decided={assessment.severity}
        floor={assessment.floor}
        alpha={assessment.alpha}
        setEmpty={assessment.set_empty ?? false}
        drawBracket
      />
      <p className="text-sm leading-relaxed">
        {how}{" "}
        <span className="text-muted-foreground">
          {lifted
            ? `On its own, the model put ${percent(assessment.probabilities[modelTop] ?? 0)} on ${modelTop}; the floor is there for cases the model has not learned.`
            : assessment.set_empty
              ? `No severity is likely enough for the ${coverage}% prediction set on its own; ${assessment.severity} is the most likely, at ${percent(assessment.confidence)}.`
              : assessment.prediction_set.length === 1
                ? `Confidence ${percent(assessment.confidence)}; only ${assessment.prediction_set[0]} is plausible at ${coverage}% confidence.`
                : `Confidence ${percent(assessment.confidence)}; at ${coverage}% confidence it is one of ${assessment.prediction_set.join(", ")}.`}
          {assessment.auditable
            ? " No LLM was involved, so the decision can be audited from rules and model alone."
            : ""}
        </span>
      </p>

      {assessment.rule_hits.length > 0 ? (
        <div className="grid gap-2">
          <Button
            size="sm"
            variant="ghost"
            // The label wraps on a narrow phone rather than push the panel wider.
            className="-mx-2 h-auto min-h-9 justify-between py-1.5 text-left whitespace-normal"
            aria-expanded={traceOpen}
            aria-controls="rule-trace"
            onClick={() => setTraceOpen(!traceOpen)}
          >
            <span>
              {assessment.rule_hits.length} {assessment.rule_hits.length === 1 ? "rule" : "rules"}{" "}
              fired; on their own they suggest {assessment.rule_severity}
            </span>
            <ChevronDownIcon
              aria-hidden
              className={cn(
                "transition-transform duration-(--duration-quick)",
                traceOpen && "rotate-180",
              )}
            />
          </Button>
          <AnimatePresence initial={false}>
            {traceOpen ? (
              <m.div
                key="rule-trace"
                id="rule-trace"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: reduceMotion ? 0 : 0.22, ease: [0.25, 1, 0.5, 1] }}
                className="grid gap-2 overflow-hidden"
              >
                <ul className="grid gap-2">
                  {assessment.rule_hits.map((hit) => (
                    <li
                      key={hit.rule_id}
                      className="grid gap-0.5 border-l-2 border-rule pl-3 text-sm"
                    >
                      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="font-medium">{hit.title}</span>
                        <span
                          className={cn(
                            "rounded-xs border px-1 text-[0.6875rem]",
                            hit.effect === "floor"
                              ? "border-sev1-fg/60 text-sev1-fg"
                              : "border-control text-muted-foreground",
                          )}
                        >
                          {hit.effect === "floor"
                            ? `floor ${hit.severity}`
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
                <div className="grid grid-cols-4 gap-1.5 pt-1" aria-label="Rule score per severity">
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
                      <span className="tabular text-[0.6875rem] text-muted-foreground">
                        {s} {(assessment.rule_scores[s] ?? 0).toFixed(1)}
                      </span>
                    </div>
                  ))}
                </div>
              </m.div>
            ) : null}
          </AnimatePresence>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No severity rule matched this window.</p>
      )}
      <p className="text-[0.6875rem] text-faint">Model {assessment.model_version}</p>
    </section>
  );
}
