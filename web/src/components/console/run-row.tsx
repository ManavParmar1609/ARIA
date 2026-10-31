import type { RunSummary } from "@/lib/api/types";
import { stripSeverity } from "@/lib/format";
import { systemName } from "@/lib/systems";

export function runTitle(run: Pick<RunSummary, "title" | "system" | "id">): string {
  const named = stripSeverity(run.title);
  if (named) return named;
  return run.system === "generic" ? "Pasted logs" : `${systemName(run.system)} logs`;
}
