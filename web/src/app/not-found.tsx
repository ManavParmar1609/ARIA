import type { Metadata } from "next";
import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { LostSpot } from "@/components/illustrations/spots";
import { ArrowCircle, Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <main className="mx-auto grid min-h-dvh max-w-2xl content-center justify-items-center gap-6 px-4 py-16 text-center">
      <Link href="/" className="rounded-sm" aria-label="ARIA home">
        <Wordmark />
      </Link>
      <LostSpot className="mt-4 h-auto w-full max-w-xs" />
      <p className="eyebrow text-muted-foreground">Error 404</p>
      <h1 className="text-[2.75rem] leading-none tracking-heading sm:text-6xl">
        This page is not here
      </h1>
      <p className="text-lg text-muted-foreground">
        The link may be out of date, or the run it pointed to was deleted.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild variant="primary" size="lg" className="pr-2">
          <Link href="/console" prefetch={false}>
            Open the console
            <ArrowCircle tone="white" />
          </Link>
        </Button>
        <Button asChild variant="ghost" size="lg">
          <Link href="/">Go to the home page</Link>
        </Button>
      </div>
    </main>
  );
}
