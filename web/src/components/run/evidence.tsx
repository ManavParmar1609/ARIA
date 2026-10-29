"use client";

import { PinIcon, XIcon } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/popover";
import type { Evidence, LogEvent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const KIND_LABEL: Record<string, string> = {
  log: "Log line",
  template: "Log template",
  feature: "Computed feature",
  rule: "Severity rule",
  model: "Model output",
  alert: "Alert",
  incident: "Past incident",
  tickets: "Ticket history",
  runbook: "Runbook",
  tool: "Tool call",
  hypothesis: "Hypothesis",
  feedback: "Reviewer feedback",
  review: "Review",
};

interface EvidenceState {
  byId: Map<string, Evidence>;
  events: LogEvent[];
  active: string | null;
  pinned: string | null;
  hover: (id: string | null) => void;
  pin: (id: string | null) => void;
  linesFor: (id: string) => LogEvent[];
}

const Ctx = createContext<EvidenceState | null>(null);

/**
 * Which evidence the reader is looking at. Hover or focus previews a citation; a click pins it
 * so it stays in the panel while the reader moves on.
 */
export function EvidenceProvider({
  evidence,
  events,
  children,
}: {
  evidence: Evidence[];
  events: LogEvent[];
  children: ReactNode;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const byId = useMemo(() => new Map(evidence.map((e) => [e.id, e])), [evidence]);
  const byTemplate = useMemo(() => {
    const map = new Map<string, LogEvent[]>();
    for (const e of events) map.set(e.template_id, [...(map.get(e.template_id) ?? []), e]);
    return map;
  }, [events]);
  const linesFor = useCallback(
    (id: string): LogEvent[] => {
      const e = byId.get(id);
      if (!e) return [];
      const data = (e.data ?? {}) as Record<string, unknown>;
      if (typeof data.line === "number") {
        const line = data.line;
        return events.filter((ev) => ev.line_no === line);
      }
      if (typeof data.template_id === "string") return byTemplate.get(data.template_id) ?? [];
      return [];
    },
    [byId, byTemplate, events],
  );
  const value = useMemo<EvidenceState>(
    () => ({
      byId,
      events,
      active: hovered ?? pinned,
      pinned,
      hover: setHovered,
      pin: setPinned,
      linesFor,
    }),
    [byId, events, hovered, pinned, linesFor],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEvidence(): EvidenceState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useEvidence needs an EvidenceProvider");
  return value;
}

function EvidencePreview({ evidence, lines }: { evidence: Evidence; lines: LogEvent[] }) {
  return (
    <div className="grid gap-2">
      <p className="text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{evidence.id}</span>{" "}
        {KIND_LABEL[evidence.kind] ?? evidence.kind}, from {evidence.source}
      </p>
      <p className="text-sm leading-snug font-medium">{evidence.title}</p>
      {evidence.detail ? (
        <p className="line-clamp-4 text-xs leading-5 whitespace-pre-wrap text-muted-foreground">
          {evidence.detail}
        </p>
      ) : null}
      <LogLines lines={lines} limit={4} wrap />
      <p className="text-[0.6875rem] text-faint">
        Click the citation to keep it in the evidence panel.
      </p>
    </div>
  );
}

/**
 * A citation. Hovering shows the evidence beside it; focusing or hovering also fills the
 * evidence panel (announced to screen readers); a click pins it there.
 */
export function EvidenceChip({ id }: { id: string }) {
  const { byId, active, pinned, hover, pin, linesFor } = useEvidence();
  const evidence = byId.get(id);
  const button = (
    <button
      type="button"
      disabled={!evidence}
      aria-pressed={pinned === id}
      aria-label={
        evidence
          ? `Evidence ${id}: ${KIND_LABEL[evidence.kind] ?? evidence.kind}, ${evidence.title}`
          : `Evidence ${id} (missing)`
      }
      aria-controls="evidence-panel"
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => hover(null)}
      onFocus={() => hover(id)}
      onBlur={() => hover(null)}
      onClick={() => {
        pin(pinned === id ? null : id);
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        document
          .getElementById("evidence-panel")
          ?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
      }}
      className={cn(
        "inline-flex h-6 items-center rounded-xs border px-1.5 align-baseline font-mono text-xs transition-colors duration-(--duration-quick)",
        !evidence && "border-danger/60 text-danger line-through",
        evidence &&
          (active === id
            ? "border-primary bg-highlight text-highlight-foreground"
            : "border-control text-muted-foreground hover:border-foreground hover:text-foreground"),
      )}
    >
      {id}
    </button>
  );
  if (!evidence) return button;
  return (
    <HoverCard openDelay={180} closeDelay={80}>
      <HoverCardTrigger asChild>{button}</HoverCardTrigger>
      <HoverCardContent side="top" className="w-96">
        <EvidencePreview evidence={evidence} lines={linesFor(id)} />
      </HoverCardContent>
    </HoverCard>
  );
}

export function Citations({ ids, className }: { ids: string[]; className?: string }) {
  if (ids.length === 0) return null;
  return (
    <span className={cn("inline-flex flex-wrap gap-1 align-baseline", className)}>
      {ids.map((id) => (
        <EvidenceChip key={id} id={id} />
      ))}
    </span>
  );
}

function DataTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.slice(0, 14).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="truncate text-muted-foreground">{key.replaceAll("_", " ")}</dt>
          <dd className="min-w-0 font-mono break-words">
            {typeof value === "object" ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function LogLines({
  lines,
  limit = 12,
  wrap = false,
  sweep = false,
}: {
  lines: LogEvent[];
  limit?: number;
  /** Wrap long lines instead of scrolling (inside hover cards, where nothing can take focus). */
  wrap?: boolean;
  /** Sweep one pass of the highlight across the lines as they appear (globals.css: .thread-pass). */
  sweep?: boolean;
}) {
  if (lines.length === 0) return null;
  const list = (
    <ol>
      {lines.slice(0, limit).map((line, i) => (
        <li
          key={line.idx}
          className={cn(
            "grid grid-cols-[2.5rem_2.75rem_1fr] gap-2 px-2",
            wrap ? "break-all whitespace-pre-wrap" : "whitespace-pre",
            sweep && "thread-pass",
          )}
          style={sweep ? ({ "--thread-i": i } as CSSProperties) : undefined}
        >
          <span className="tabular text-right text-faint">{line.line_no ?? line.idx + 1}</span>
          <span
            className={
              line.level === "WARN"
                ? "text-sev2-fg"
                : line.level && /ERR|FATAL|CRIT|SEVERE/.test(line.level)
                  ? "text-sev1-fg"
                  : "text-faint"
            }
          >
            {line.level ?? ""}
          </span>
          <span>{line.message}</span>
        </li>
      ))}
    </ol>
  );
  const frame =
    "rounded-sm border border-rule bg-sunken py-1.5 font-mono text-[0.6875rem] leading-5";
  return (
    <div className="grid gap-1">
      {wrap ? (
        <div className={frame}>{list}</div>
      ) : (
        <div
          tabIndex={0}
          role="region"
          aria-label="Log lines"
          className={cn(frame, "overflow-x-auto")}
        >
          {list}
        </div>
      )}
      {lines.length > limit ? (
        <p className="text-xs text-muted-foreground">
          and {(lines.length - limit).toLocaleString("en")} more lines like these
        </p>
      ) : null}
    </div>
  );
}

/** The evidence behind whatever citation the reader is pointing at. */
export function EvidencePanel({ className }: { className?: string }) {
  const { active, pinned, byId, pin, linesFor } = useEvidence();
  const evidence = active ? byId.get(active) : undefined;
  return (
    <section
      id="evidence-panel"
      aria-label="Evidence"
      aria-live="polite"
      className={cn("grid min-w-0 content-start gap-3 rounded-lg bg-raised p-4 sm:p-5", className)}
    >
      {evidence ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="grid gap-1">
              <p className="text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{evidence.id}</span>{" "}
                {KIND_LABEL[evidence.kind] ?? evidence.kind}, from {evidence.source}
              </p>
              <h3 className="text-sm leading-snug font-medium">{evidence.title}</h3>
            </div>
            {pinned === evidence.id ? (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Unpin evidence"
                onClick={() => pin(null)}
              >
                <XIcon aria-hidden />
              </Button>
            ) : (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Pin this evidence"
                onClick={() => pin(evidence.id)}
              >
                <PinIcon aria-hidden />
              </Button>
            )}
          </div>
          {evidence.detail ? (
            <pre
              tabIndex={0}
              role="region"
              aria-label="Evidence detail"
              className="max-h-48 overflow-auto rounded-sm bg-sunken p-2 text-xs leading-5 whitespace-pre-wrap"
            >
              {evidence.detail}
            </pre>
          ) : null}
          {/* Keyed by evidence, so each citation pointed at sends its own pass of light. */}
          <LogLines key={evidence.id} lines={linesFor(evidence.id)} sweep />
          <DataTable data={(evidence.data ?? {}) as Record<string, unknown>} />
        </>
      ) : (
        <div className="grid gap-1.5">
          <h3 className="text-sm font-medium">Evidence</h3>
          <p className="text-sm text-muted-foreground">
            Every claim in the report cites evidence like{" "}
            <span className="rounded-xs border border-control px-1 font-mono text-xs">E3</span>.
            Point at one, or focus it with the keyboard, to see what it rests on; click to keep it
            here.
          </p>
        </div>
      )}
    </section>
  );
}
