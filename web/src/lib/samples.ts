import loaders from "@/data/sample-lines";
import index from "@/data/samples.json";

/** What a sample log holds: an incident, or routine noise that needs no action. */
export type SampleKind = "incident" | "routine";

/** A log the console ships to try (scripts/export_web_samples.py): real Loghub lines arranged
 * into a window, so a run started from one is marked as built from a sample. */
export interface SampleLog {
  id: string;
  /** What the log shows, in plain words, without the name of the system that wrote it. */
  label: string;
  system: string;
  kind: SampleKind;
}

/** Every sample, without its lines: all a page carries until someone picks one. */
export const SAMPLE_LOGS: readonly SampleLog[] = index.map((entry) => ({
  ...entry,
  kind: entry.kind === "routine" ? "routine" : "incident",
}));

/** A sample's lines, fetched the first time they are asked for: each sample's lines are a chunk
 * of their own (src/data/sample-lines.ts). */
export async function sampleLines(id: string): Promise<string[]> {
  const load = loaders.get(id);
  if (!load) throw new Error(`There is no sample called ${id}.`);
  return (await load()).default.lines;
}
