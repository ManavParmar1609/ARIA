"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useMemo, useRef, useState } from "react";

import { SeverityScale, TagStrip } from "@/components/aria/severity";
import type { Replay } from "@/lib/site-data";
import { cn } from "@/lib/utils";

gsap.registerPlugin(useGSAP);

const KIND_LABEL: Record<string, string> = {
  feature: "computed feature",
  template: "log template",
  log: "log line",
  rule: "severity rule",
  model: "model output",
  incident: "past incident",
  runbook: "runbook",
  tool: "tool call",
  hypothesis: "hypothesis",
};

const DECIDED: Record<string, string> = {
  rules: "Rules decided it.",
  model: "The calibrated model decided it.",
  fallback: "Too uncertain to decide alone, so a person confirms.",
  llm: "The LLM chose within the model's prediction set.",
};

/**
 * The landing page's hero: one recorded run as a triage tag next to its log. Hovering or
 * focusing a citation lights up the lines it points to and shows the evidence.
 */
export function TriageReplay({ data }: { data: Replay }) {
  const root = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const active = hovered ?? pinned;
  const lit = useMemo(
    () => new Set(active ? (data.evidence[active]?.lines ?? []) : []),
    [active, data.evidence],
  );
  const evidence = active ? data.evidence[active] : undefined;
  const p = Math.round((data.probabilities[data.severity] ?? 0) * 100);
  const firstShown = data.lines[0]?.lineNo ?? 1;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const show = { autoAlpha: 1, x: 0, y: 0 };
        gsap
          .timeline({ defaults: { ease: "power3.out" } })
          .fromTo(
            "[data-anim=line]",
            { autoAlpha: 0, y: 6 },
            { ...show, duration: 0.3, stagger: 0.05 },
          )
          .fromTo(
            "[data-anim=flag]",
            { autoAlpha: 0, x: -8 },
            { ...show, duration: 0.35 },
            "-=0.05",
          )
          .fromTo("[data-anim=tag]", { autoAlpha: 0, y: 28 }, { ...show, duration: 0.7 }, "-=0.15")
          .fromTo(
            "[data-anim=tag] [data-bar]",
            { scaleY: 0 },
            { scaleY: 1, transformOrigin: "bottom", duration: 0.6, stagger: 0.07 },
            "-=0.35",
          )
          .fromTo(
            "[data-anim=claim]",
            { autoAlpha: 0, y: 8 },
            { ...show, duration: 0.4, stagger: 0.09 },
            "-=0.3",
          )
          .fromTo("[data-anim=status]", { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.4 });
      });
      return () => mm.revert();
    },
    { scope: root },
  );

  const chip = (id: string) => {
    const known = id in data.evidence;
    return (
      <button
        key={id}
        type="button"
        disabled={!known}
        aria-pressed={pinned === id}
        aria-describedby="replay-evidence"
        onMouseEnter={() => setHovered(id)}
        onMouseLeave={() => setHovered(null)}
        onFocus={() => setHovered(id)}
        onBlur={() => setHovered(null)}
        onClick={() => setPinned((current) => (current === id ? null : id))}
        className={cn(
          "inline-flex h-6 items-center rounded-xs border px-1.5 align-baseline font-mono text-xs transition-colors duration-(--duration-quick)",
          active === id
            ? "border-primary bg-highlight text-highlight-foreground"
            : "border-control text-muted-foreground hover:border-foreground hover:text-foreground",
        )}
      >
        {id}
      </button>
    );
  };

  return (
    <div ref={root} className="relative">
      {/* the log the tag was written from */}
      <div className="rounded-md border border-rule bg-sunken">
        <div className="flex items-baseline justify-between gap-4 border-b border-rule px-4 py-2.5 text-xs text-muted-foreground">
          <span className="font-mono">hdfs.log</span>
          <span className="tabular">
            lines {firstShown} to {firstShown + 8} and {data.lines.at(-1)?.lineNo} of {data.nLines}
          </span>
        </div>
        <ol
          className="py-2 font-mono text-[0.75rem] leading-6"
          aria-label="Log lines from the recorded run"
        >
          {data.lines.map((line, i) => {
            const isLit = lit.has(line.lineNo);
            const gap = i > 0 && line.lineNo - (data.lines[i - 1]?.lineNo ?? 0) > 1;
            return (
              <li key={line.lineNo} data-anim="line">
                {gap ? (
                  <span className="grid grid-cols-[2.25rem_1fr] px-4 text-faint" aria-hidden>
                    <span className="text-right">&#8942;</span>
                  </span>
                ) : null}
                <span
                  className={cn(
                    "grid grid-cols-[2.25rem_3rem_1fr] items-baseline gap-2 border-l-2 px-4 transition-colors duration-(--duration-quick)",
                    isLit ? "border-primary bg-highlight" : "border-transparent",
                    line.quarantined && "text-muted-foreground",
                  )}
                >
                  <span className="tabular text-right text-faint">{line.lineNo}</span>
                  <span className={cn(line.level === "WARN" ? "text-sev2-fg" : "text-faint")}>
                    {line.level}
                  </span>
                  <span
                    className={cn(
                      "truncate",
                      line.quarantined && "line-through decoration-danger/70",
                    )}
                  >
                    {line.text}
                  </span>
                </span>
                {line.quarantined ? (
                  <span
                    data-anim="flag"
                    className="mx-4 mt-1 mb-1 ml-[6.75rem] inline-flex items-center gap-1.5 rounded-xs border border-danger/60 px-1.5 font-sans text-[0.6875rem] font-medium text-danger"
                  >
                    Quarantined: reads like an instruction, not a log
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
        <p
          id="replay-evidence"
          aria-live="polite"
          className="min-h-16 border-t border-rule px-4 pt-3 pb-9 text-xs leading-relaxed text-muted-foreground"
        >
          {evidence ? (
            <>
              <span className="font-mono text-foreground">{evidence.id}</span>{" "}
              <span>({KIND_LABEL[evidence.kind] ?? evidence.kind})</span>{" "}
              <span className="text-foreground">{evidence.title}</span>
              {evidence.lines.length > 1 ? (
                <span> {evidence.lines.length} lines in this window carry it.</span>
              ) : null}
            </>
          ) : (
            "Point at a citation on the tag to see the evidence behind the claim."
          )}
        </p>
      </div>

      {/* the tag ARIA wrote */}
      <article
        data-anim="tag"
        aria-label={`Triage tag: ${data.severity}, ${data.title}`}
        className="relative z-10 -mt-6 ml-0 flex overflow-hidden rounded-md border border-rule bg-raised shadow-2xl shadow-black/25 sm:ml-10 lg:-ml-8 xl:ml-10"
      >
        <TagStrip severity={data.severity} className="w-14 sm:w-16" />
        <div className="min-w-0 flex-1 p-4 sm:p-5">
          <h2 className="text-lg leading-snug font-bold">{data.title}</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {data.system}, a {data.windowMinutes}-minute window of {data.nLines} lines
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,13rem)_1fr] sm:items-end">
            <SeverityScale
              probabilities={data.probabilities}
              predictionSet={data.predictionSet}
              decided={data.severity}
              compact
            />
            <p className="text-sm leading-relaxed">
              <span className="font-semibold">
                {data.severity}, {p}% likely.
              </span>{" "}
              <span className="text-muted-foreground">{DECIDED[data.decidedBy] ?? ""}</span>
            </p>
          </div>
          <ul className="mt-4 grid gap-2.5 border-t border-rule pt-4 text-sm leading-relaxed">
            {data.claims.map((claim) => (
              <li key={claim.text} data-anim="claim" className="grid grid-cols-[0.75rem_1fr] gap-2">
                <span aria-hidden className="mt-2.5 block size-1.5 rounded-full bg-control" />
                <span>
                  {claim.text}{" "}
                  <span className="inline-flex flex-wrap gap-1 align-baseline">
                    {claim.evidence.slice(0, 3).map(chip)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <div
            data-anim="status"
            className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-4"
          >
            <span className="inline-flex items-center gap-2 text-sm font-medium">
              <span
                aria-hidden
                className="block size-2 animate-pulse-dot rounded-full bg-primary"
              />
              Waiting for a person to approve
            </span>
            <span className="tabular text-xs text-muted-foreground">
              ready for review {(data.timeToReviewMs / 1000).toFixed(1)} s after the logs arrived
            </span>
          </div>
        </div>
      </article>
    </div>
  );
}
