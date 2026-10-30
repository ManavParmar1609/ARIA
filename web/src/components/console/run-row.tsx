import Link from "next/link";

import { RunStatus } from "@/components/console/status";
import { SEVERITY_BG } from "@/components/aria/severity";
import { Button } from "@/components/ui/button";
import { isSeverity, type RunSummary } from "@/lib/api/types";
import { absoluteTime, relativeTime, stripSeverity } from "@/lib/format";
import { systemName, triggerLabel } from "@/lib/systems";
import { cn } from "@/lib/utils";

export function runTitle(run: Pick<RunSummary, "title" | "system" | "id">): string {
  return stripSeverity(run.title) || `${systemName(run.system)} logs`;
}

/** A run as a card: severity strip, what happened, and what it needs from you. */
export function RunRow({ run, action }: { run: RunSummary; action?: "review" | "open" }) {
  const sev = isSeverity(run.severity) ? run.severity : null;
  const href = `/console/runs/${encodeURIComponent(run.id)}`;
  return (
    <li className="group relative flex overflow-hidden rounded-lg bg-raised transition-colors duration-(--duration-quick) focus-within:ring-2 focus-within:ring-ring hover:bg-raised/80">
      <div
        className={cn(
          "tabular flex w-11 shrink-0 items-start justify-center pt-4 text-xs font-medium sm:w-14",
          sev ? cn(SEVERITY_BG[sev], "text-sev-ink") : "bg-sunken text-faint",
        )}
      >
        {sev ?? "—"}
      </div>
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
        <div className="grid min-w-0 gap-0.5">
          <Link
            href={href as never}
            className="line-clamp-2 font-medium text-heading outline-none after:absolute after:inset-0 after:content-[''] sm:line-clamp-1"
          >
            {runTitle(run)}
          </Link>
          <p className="truncate text-sm text-muted-foreground">
            {systemName(run.system)}, {triggerLabel(run.trigger)},{" "}
            <time dateTime={run.created_at} title={absoluteTime(run.created_at)}>
              {relativeTime(run.created_at)}
            </time>
          </p>
        </div>
        <div className="relative z-10 flex items-center gap-3">
          {action === "review" ? null : <RunStatus status={run.status} />}
          {action === "review" ? (
            <Button asChild size="sm" variant="secondary">
              <Link href={href as never}>Review</Link>
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
