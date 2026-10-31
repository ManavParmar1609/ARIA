import type { Metadata } from "next";
import Link from "next/link";

import { LostSpot } from "@/components/illustrations/spots";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

export default function ConsoleNotFound() {
  return (
    <div className="grid max-w-xl justify-items-start gap-5 py-8">
      <LostSpot className="h-auto w-full max-w-60" />
      <h1 className="text-3xl leading-tight tracking-heading">This page is not in the console</h1>
      <p className="text-muted-foreground">
        The link may be out of date. Every page is in the menu, and Search at the top of it finds
        pages, incidents and samples.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button asChild variant="primary">
          <Link href="/console/runs">Your incidents</Link>
        </Button>
        <Button asChild variant="ghost">
          <Link href="/console/runs/new">Start a triage</Link>
        </Button>
      </div>
    </div>
  );
}
