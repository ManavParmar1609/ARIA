import type { Metadata } from "next";

import { RunView } from "@/components/run/run-view";
import { evaluation } from "@/lib/site-data";

// The page names the tab after the incident once it loads (useDocumentTitle).
export const metadata: Metadata = { title: "Incident" };

export default async function RunPage(props: PageProps<"/console/runs/[runId]">) {
  const { runId } = await props.params;
  // Read here, on the server, so the page carries the one figure and not the results file.
  const shortListHeld = evaluation().severity.coverageWithFloors;
  return <RunView runId={decodeURIComponent(runId)} shortListHeld={shortListHeld} />;
}
