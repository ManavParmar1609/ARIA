import type { Metadata } from "next";
import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <main className="mx-auto grid min-h-dvh max-w-2xl content-center justify-items-center gap-6 px-4 py-16 text-center">
      <Link href="/" className="rounded-sm text-heading" aria-label="ARIA home">
        <Wordmark />
      </Link>
      <p className="eyebrow mt-6 text-muted-foreground">Error 404</p>
      <h1 className="text-4xl leading-none tracking-heading sm:text-5xl sm:tracking-display">
        This page is not here
      </h1>
      <p className="text-lg text-muted-foreground">
        The link may be out of date, or the run it pointed to was deleted.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild variant="primary">
          <Link href="/console" prefetch={false}>
            Open the console
          </Link>
        </Button>
        <Button asChild variant="ghost">
          <Link href="/">Go to the home page</Link>
        </Button>
      </div>
    </main>
  );
}
