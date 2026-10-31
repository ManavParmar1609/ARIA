import type { Metadata } from "next";

import { Guide } from "@/components/console/guide";

export const metadata: Metadata = { title: "Guide" };

// Only an incident's own page may be the way back: anything else in ?from= is ignored.
const INCIDENT_PATH = /^\/console\/runs\/[\w.-]{1,128}$/;

export default async function GuidePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { from } = await searchParams;
  return <Guide back={typeof from === "string" && INCIDENT_PATH.test(from) ? from : null} />;
}
