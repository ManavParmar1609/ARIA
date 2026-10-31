import Link from "next/link";

import { ArrowCircle, Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { REPO_URL } from "@/lib/site-data";

// The README's offline quick start, without keys, from a fresh clone (NV-m11).
const QUICKSTART = [
  `git clone ${REPO_URL}.git`,
  "cd ARIA",
  "make install",
  "uv run aria db upgrade && uv run aria seed",
  "make dev",
];

/** The last panel: one action, and the commands to run it yourself. */
export function Closing() {
  return (
    <section
      aria-labelledby="try-title"
      className="mx-auto max-w-[75rem] px-3 pb-16 sm:px-6 lg:pb-20"
    >
      <div className="relative overflow-hidden rounded-card bg-panel-sage px-7 py-10 sm:px-12 sm:py-14">
        <div className="relative grid gap-6 lg:grid-cols-2 lg:items-end lg:gap-12">
          <div className="grid gap-5">
            <h2 id="try-title" className="text-section max-w-[16ch]">
              Let ARIA take the first look.
            </h2>
            <p className="max-w-[44ch] text-lg leading-relaxed text-heading">
              Try it here, or on your own machine. It works offline with no key; with one, a
              language model investigates and writes.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="primary" size="lg">
                <Link href="/console" prefetch={false}>
                  Open the console
                  <ArrowCircle />
                </Link>
              </Button>
              <Button asChild variant="raised" size="lg">
                <a href={`${REPO_URL}#quickstart`}>Read the quick start</a>
              </Button>
            </div>
          </div>
          {/* Long commands wrap (with a hanging indent) rather than scroll, so phones need no
              sideways scrolling inside the block. */}
          <div className="grid rounded-[12px] bg-raised">
            <div className="flex items-center justify-between gap-3 pt-1.5 pr-1.5 pl-5">
              <span className="text-sm text-muted-foreground">
                On your own machine (Python 3.12 with uv, Node 22 with pnpm)
              </span>
              <CopyButton text={QUICKSTART.join("\n")} label="the commands" />
            </div>
            <pre className="px-5 pt-1 pb-4 text-left text-xs leading-relaxed whitespace-pre-wrap text-foreground">
              <code>
                {QUICKSTART.map((command) => (
                  <span key={command} className="block pl-[2ch] -indent-[2ch]">
                    <span aria-hidden className="text-faint select-none">
                      ${" "}
                    </span>
                    {command}
                  </span>
                ))}
              </code>
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}
