import type { Metadata } from "next";

import { RunView } from "@/components/run/run-view";

// The page names the tab after the incident once it loads (useDocumentTitle).
export const metadata: Metadata = { title: "Incident" };

export default async function RunPage(props: PageProps<"/console/runs/[runId]">) {
  const { runId } = await props.params;
  return <RunView runId={decodeURIComponent(runId)} />;
}
