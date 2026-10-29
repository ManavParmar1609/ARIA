import type { Metadata } from "next";

import { RunView } from "@/components/run/run-view";

export async function generateMetadata(
  props: PageProps<"/console/runs/[runId]">,
): Promise<Metadata> {
  const { runId } = await props.params;
  return { title: `Run ${decodeURIComponent(runId)}` };
}

export default async function RunPage(props: PageProps<"/console/runs/[runId]">) {
  const { runId } = await props.params;
  return <RunView runId={decodeURIComponent(runId)} />;
}
