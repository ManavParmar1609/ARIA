import type { Metadata } from "next";

import { RunbookDetail } from "@/components/console/runbooks";

export async function generateMetadata(
  props: PageProps<"/console/runbooks/[slug]">,
): Promise<Metadata> {
  const { slug } = await props.params;
  return { title: `Runbook ${decodeURIComponent(slug)}` };
}

export default async function RunbookPage(props: PageProps<"/console/runbooks/[slug]">) {
  const { slug } = await props.params;
  return <RunbookDetail slug={decodeURIComponent(slug)} />;
}
