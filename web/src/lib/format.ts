const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

/** "3 minutes ago", "yesterday". */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  if (Math.abs(seconds) < 30) return "just now";
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return rtf.format(Math.round(seconds / size), unit);
    }
  }
  return "";
}

/** "29 Oct 2026, 07:41:12" in the reader's time zone. */
export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** "00:42": the time of day to the minute, for a sentence ("approved by you at 00:42"). */
export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** A log pattern as people read it: each part that varies ("<*>") becomes "…". */
export const plainTemplate = (template: string): string => template.replaceAll("<*>", "…");

/** How long a stretch of logs spans: "under a minute", "1 minute", "7.7 minutes". */
export function minutesWords(seconds: number): string {
  if (seconds < 60) return "under a minute";
  const minutes = Number((seconds / 60).toFixed(1));
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

/** 734 -> "734 ms", 12_400 -> "12.4 s", 193_000 -> "3 min 13 s", 7_260_000 -> "2 h 1 min". */
export function duration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 9.95) return `${s.toFixed(1)} s`;
  // Round once, to whole seconds, so 59.6 s reads "1 min", never "60 s" or "0 min 60 s".
  const total = Math.round(s);
  if (total < 60) return `${total} s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h) return m ? `${h} h ${m} min` : `${h} h`;
  const rest = total % 60;
  return rest ? `${m} min ${rest} s` : `${m} min`;
}

export function percent(x: number | null | undefined, digits = 0): string {
  if (x == null || Number.isNaN(x)) return "";
  return `${(x * 100).toFixed(digits)}%`;
}

export function money(usd: number | null | undefined): string {
  if (usd == null) return "";
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en")} ${n === 1 ? one : many}`;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? (sorted[mid] ?? null)
    : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

/** True when ARIA's evidence template wrote the report: no LLM, or the offline stand-in for one. */
export function writtenOffline(
  report: { generated_by?: string | null; model?: string | null } | null | undefined,
): boolean {
  return !report || report.generated_by !== "llm" || /^fake\//.test(report.model ?? "");
}

/** "SEV1", "SEV1 and SEV2", "SEV1, SEV2 and SEV3". */
export function listed(items: string[]): string {
  return items.length < 3
    ? items.join(" and ")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Report titles lead with the severity ("SEV3 · ..."); the UI shows severity separately. */
export function stripSeverity(title: string | null | undefined): string {
  return (title ?? "").replace(/^SEV[1-4]\s*·\s*/, "");
}

/** A past incident's fix as a person reads it: steps a sample's runbook recorded lose the
 * runbook's ID ("Followed runbook zookeeper-quorum-loss: ..."), and steps that ended in a full
 * stop read "first; restart", not "first.; Restart". */
export function plainResolution(text: string | null | undefined): string {
  return (text ?? "")
    .replace(/^Followed runbook \S+:\s*/, "")
    .replace(/\.;\s*(\S)/g, (_, next: string) => `; ${next.toLowerCase()}`)
    .replace(/\.\.$/, ".");
}

const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

/** A count as prose writes it: words below ten ("six benchmarks"), digits from ten on. */
export function count(n: number): string {
  return (Number.isInteger(n) && WORDS[n]) || n.toLocaleString("en");
}

/** A reviewer as a person reads them: the name they signed in with, "the operator" for a review
 * made from the command line (as the seeded examples were), "a reviewer" when nobody signed in. */
export function reviewerName(reviewer: string | null | undefined): string {
  if (!reviewer || reviewer === "anonymous") return "a reviewer";
  return reviewer === "cli" ? "the operator, from the command line" : reviewer;
}

/** What a reviewer did, in a past-tense phrase: "approve" reads "approved". */
export function decisionWords(decision: string): string {
  return (
    { approve: "approved", reject: "discarded", edit: "edited and approved" }[decision] ?? decision
  );
}

/** A phrase with its first letter in capitals, to start a sentence. */
export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
