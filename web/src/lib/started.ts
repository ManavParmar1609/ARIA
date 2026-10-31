// Incidents this tab started. Their page plays the steps back at a pace a person can follow,
// even when ARIA finished before the page loaded (an offline triage takes under a second). Kept
// in memory only: a reload or another tab opens the incident as it is.
const started = new Set<string>();

export function markStarted(runId: string): void {
  started.add(runId);
}

export function wasStarted(runId: string): boolean {
  return started.has(runId);
}

/** Once played back, an incident opens as it is when the visitor comes back to it. */
export function forgetStarted(runId: string): void {
  started.delete(runId);
}
