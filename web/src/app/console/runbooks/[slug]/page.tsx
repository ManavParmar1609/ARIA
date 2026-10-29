import type { Metadata } from "next";

import { RunbookDetail } from "@/components/console/runbooks";

// The page names the tab after the runbook once it loads (useDocumentTitle).
export const metadata: Metadata = { title: "Runbook" };

export default async function RunbookPage(props: PageProps<"/console/runbooks/[slug]">) {
  const { slug } = await props.params;
  return <RunbookDetail slug={decodeURIComponent(slug)} />;
}
