"use client";

import { useMemo, useRef, useState, type CSSProperties } from "react";

import { SeverityScale, TagStrip } from "@/components/aria/severity";
import { useWideMotion } from "@/lib/motion";
import type { Replay } from "@/lib/site-data";
import { cx } from "@/lib/cx";

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
 * One recorded run as a triage tag beside the log it was written from. Hovering or focusing a
 * citation lights up the lines it points to and shows the evidence.
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
  // Each lit line's place in the order the highlight sweeps onto them.
  const litOrder = useMemo(() => {
    const order = new Map<number, number>();
    for (const line of data.lines) if (lit.has(line.lineNo)) order.set(line.lineNo, order.size);
    return order;
  }, [lit, data.lines]);
  const evidence = active ? data.evidence[active] : undefined;
  const p = Math.round((data.probabilities[data.severity] ?? 0) * 100);
  const firstShown = data.lines[0]?.lineNo ?? 1;

  // Wide screens play the run in as it scrolls into view: lines, the flagged line, the tag's
  // bars, then the claims.
  useWideMotion(root, ({ gsap }) => {
    const show = { autoAlpha: 1, x: 0, y: 0 };
    gsap.set("[data-tag] [data-stamp]", { autoAlpha: 0 });
    gsap
      .timeline({
        defaults: { ease: "power3.out" },
        scrollTrigger: { trigger: root.current, start: "top 75%", once: true },
      })
      .fromTo("[data-anim=line]", { autoAlpha: 0, y: 6 }, { ...show, duration: 0.3, stagger: 0.05 })
      .fromTo("[data-anim=flag]", { autoAlpha: 0, x: -8 }, { ...show, duration: 0.35 }, "-=0.05")
      .fromTo(
        "[data-tag] [data-bar]",
        { scaleY: 0 },
        { scaleY: 1, transformOrigin: "bottom", duration: 0.6, stagger: 0.07 },
        "-=0.35",
      )
      // the severity lands like a rubber stamp (it scales and turns but never fades, so its label
      // keeps its contrast), then the prediction-set bracket draws across
      .set("[data-tag] [data-stamp]", { autoAlpha: 1 }, "-=0.2")
      .fromTo(
        "[data-tag] [data-stamp]",
        { scale: 2, rotation: -12 },
        { scale: 1, rotation: 0, duration: 0.5, ease: "back.out(2.2)" },
        "<",
      )
      .fromTo(
        "[data-tag] [data-bracket]",
        { scaleX: 0 },
        { scaleX: 1, transformOrigin: "left center", duration: 0.5, ease: "power2.inOut" },
        "-=0.15",
      )
      .fromTo(
        "[data-anim=claim]",
        { autoAlpha: 0, y: 8 },
        { ...show, duration: 0.4, stagger: 0.09 },
        "-=0.3",
      )
      .fromTo("[data-anim=status]", { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.4 })
      // the waiting dot pulses three times as the status appears, then rests
      .to("[data-pulse]", {
        opacity: 0.35,
        duration: 0.8,
        ease: "sine.inOut",
        repeat: 5,
        yoyo: true,
      });
  });

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
        className={cx(
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
    <div
      ref={root}
      className="grid items-start gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-8"
    >
      {/* the log the tag was written from */}
      <div className="overflow-hidden rounded-lg bg-raised">
        <div className="flex items-baseline justify-between gap-4 border-b border-rule px-5 py-3 text-xs text-muted-foreground">
          <span className="font-mono">hdfs.log</span>
          <span className="tabular">
            lines {firstShown} to {firstShown + 8} and {data.lines.at(-1)?.lineNo} of {data.nLines}
          </span>
        </div>
        <ol
          className="py-3 font-mono text-[0.75rem] leading-6"
          aria-label="Log lines from the recorded run"
        >
          {/* the evidence thread sweeps the highlight onto each cited line in order */}
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
                  className={cx(
                    "grid grid-cols-[2.25rem_1fr] items-baseline gap-2 border-l-2 px-4 transition-colors duration-(--duration-quick) sm:grid-cols-[2.25rem_3rem_1fr]",
                    isLit
                      ? "thread-lit border-primary text-highlight-foreground [&>span]:text-highlight-foreground"
                      : "border-transparent",
                    line.quarantined && !isLit && "text-muted-foreground",
                  )}
                  style={
                    isLit
                      ? ({ "--thread-i": litOrder.get(line.lineNo) ?? 0 } as CSSProperties)
                      : undefined
                  }
                >
                  <span className="tabular text-right text-faint">{line.lineNo}</span>
                  {/* On a phone the level gives way, so the line itself has room to be read. */}
                  <span
                    className={cx(
                      "hidden sm:inline",
                      line.level === "WARN" ? "text-sev2-fg" : "text-faint",
                    )}
                  >
                    {line.level}
                  </span>
                  <span
                    className={cx(
                      "break-all sm:truncate",
                      line.quarantined && "line-through decoration-danger/70",
                    )}
                  >
                    {line.text}
                  </span>
                </span>
                {line.quarantined ? (
                  <span
                    data-anim="flag"
                    className="mx-4 mt-1 mb-1 ml-[3.25rem] inline-flex items-center gap-1.5 rounded-xs border border-danger/60 px-1.5 font-sans text-xs font-medium text-danger sm:ml-[6.75rem]"
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
          className="min-h-20 border-t border-rule px-5 py-4 text-sm leading-relaxed text-muted-foreground"
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
            "Point at a citation on the tag to see the evidence behind its claim."
          )}
        </p>
      </div>

      {/* the tag ARIA wrote */}
      <article
        data-tag
        aria-label={`Triage tag: ${data.severity}, ${data.title}`}
        className="flex overflow-hidden rounded-lg bg-raised"
      >
        <TagStrip severity={data.severity} className="w-12 sm:w-14" />
        <div className="min-w-0 flex-1 p-5 sm:p-6">
          <h3 className="text-xl leading-snug tracking-heading">{data.title}</h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {data.system}, a {data.windowMinutes}-minute window of {data.nLines} lines
          </p>
          <div className="mt-4 grid gap-4">
            <SeverityScale
              probabilities={data.probabilities}
              predictionSet={data.predictionSet}
              decided={data.severity}
              compact
            />
            <p className="text-sm leading-relaxed">
              <span className="font-medium">
                {data.severity}, {p}% likely.
              </span>{" "}
              <span className="text-muted-foreground">{DECIDED[data.decidedBy] ?? ""}</span>
            </p>
          </div>
          <h4 className="eyebrow mt-5 border-t border-rule pt-5 text-muted-foreground">
            Claims and the evidence they cite
          </h4>
          <ul className="mt-3 grid gap-2.5 text-sm leading-relaxed">
            {data.claims.map((claim) => (
              <li key={claim.text} data-anim="claim" className="grid grid-cols-[0.75rem_1fr] gap-2">
                <span aria-hidden className="mt-2.5 block size-1.5 rounded-full bg-foreground/70" />
                <span>
                  {claim.text}{" "}
                  <span className="inline-flex flex-wrap gap-1 align-baseline">
                    {claim.evidence.slice(0, 3).map(chip)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {/* On a phone the log, and its evidence line, sit far above the tag, so a tapped
              citation shows its evidence here too. Screen readers already hear the log's line. */}
          {evidence ? (
            <p
              aria-hidden
              className="mt-3 rounded-md bg-sunken px-3 py-2 text-sm leading-relaxed text-muted-foreground lg:hidden"
            >
              <span className="font-mono text-foreground">{evidence.id}</span>{" "}
              <span className="text-foreground">{evidence.title}</span>
            </p>
          ) : null}
          <div
            data-anim="status"
            className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-5"
          >
            <span className="inline-flex items-center gap-2 text-sm font-medium">
              <span
                aria-hidden
                data-pulse
                className="block size-2.5 rounded-full bg-grass ring-1 ring-pop-ink/40"
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
