/** What a queued incident waits for (item 31): the server runs a few triages at a time. */
export function waitingText(ahead: number | null | undefined): string {
  if (!ahead) return "It starts in a moment.";
  const others = ahead === 1 ? "1 triage is" : `${ahead.toLocaleString("en")} triages are`;
  return `ARIA is busy: ${others} ahead of yours. Yours starts as soon as a place is free.`;
}
