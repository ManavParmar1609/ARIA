"use client";

import { ChevronDownIcon } from "lucide-react";
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
  const coverage = Math.round((1 - assessment.alpha) * 100);
  const how =
    assessment.decided_by === "fallback" && assessment.set_empty
      ? "ARIA was not sure enough to decide alone, so it took the most likely class and asked for review."
      : (HOW[assessment.decided_by] ?? assessment.decided_by);
  const maxScore = Math.max(1, ...SEVERITIES.map((s) => assessment.rule_scores[s] ?? 0));
  return (
    <section
      aria-labelledby="severity-title"
      className="grid gap-4 rounded-md border border-rule bg-raised p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1">
          <h2 id="severity-title" className="text-sm font-semibold">
            Severity
          </h2>
          <p className="text-xs text-muted-foreground">{SEVERITY_MEANING[assessment.severity]}</p>
        </div>
        <SeverityBadge severity={assessment.severity} />
      </div>
      <SeverityScale
        probabilities={assessment.probabilities}
        predictionSet={assessment.prediction_set}
        decided={assessment.severity}
        floor={assessment.floor}
        alpha={assessment.alpha}
        setEmpty={assessment.set_empty ?? false}
      />
      <p className="text-sm leading-relaxed">
        {how}{" "}
        <span className="text-muted-foreground">
          {assessment.set_empty
            ? `No severity is likely enough for the ${coverage}% prediction set on its own; ${assessment.severity} is the most likely, at ${percent(assessment.confidence)}.`
            : `Confidence ${percent(assessment.confidence)}; the ${coverage}% set is {${assessment.prediction_set.join(", ")}}.`}
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
            className="-mx-2 justify-between"
            aria-expanded={traceOpen}
            aria-controls="rule-trace"
            onClick={() => setTraceOpen(!traceOpen)}
          >
            <span>
              Rule trace: {assessment.rule_hits.length}{" "}
              {assessment.rule_hits.length === 1 ? "rule" : "rules"}, pointing to{" "}
              {assessment.rule_severity}
            </span>
            <ChevronDownIcon
              aria-hidden
              className={cn(
                "transition-transform duration-(--duration-quick)",
                traceOpen && "rotate-180",
              )}
            />
          </Button>
          {traceOpen ? (
            <div id="rule-trace" className="grid gap-2">
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
                        style={{ width: `${((assessment.rule_scores[s] ?? 0) / maxScore) * 100}%` }}
                      />
                    </div>
                    <span className="tabular text-[0.6875rem] text-muted-foreground">
                      {s} {(assessment.rule_scores[s] ?? 0).toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No severity rule matched this window.</p>
      )}
      <p className="text-[0.6875rem] text-faint">Model {assessment.model_version}</p>
    </section>
  );
}
