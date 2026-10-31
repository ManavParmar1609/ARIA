import Link from "next/link";

import { Converge } from "@/components/site/line-art";
import { ArrowCircle, Button } from "@/components/ui/button";
import { REPO_URL } from "@/lib/site-data";

// The README's offline quick start, without keys.
const QUICKSTART = ["make install", "uv run aria db upgrade && uv run aria seed", "make dev"];

/** The last panel: one action, the three commands behind it, and the lines running together. */
export function Closing() {
  return (
    <section aria-labelledby="try-title" className="mx-auto max-w-[75rem] px-3 pb-6 sm:px-6">
      <div className="relative overflow-hidden rounded-card bg-panel-sage px-7 pt-12 pb-0 sm:px-12 sm:pt-16">
        <div className="relative grid gap-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:items-end lg:gap-12">
          <div className="grid gap-5">
            <span className="tag justify-self-start bg-raised">Try it</span>
            <h2 id="try-title" className="text-display max-w-[14ch]">
              Let ARIA take the first look.
            </h2>
            <p className="max-w-[46ch] text-[0.9375rem] leading-relaxed text-heading">
              Try it here, or on your own machine with these three commands. It works offline with
              no key, and with one, a language model investigates and writes.
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
          <pre className="rounded-[12px] bg-raised px-5 py-4 text-left text-sm leading-relaxed whitespace-pre-wrap text-foreground">
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
        <Converge className="mt-12 -mr-12 w-full text-heading sm:mt-14" />
      </div>
    </section>
  );
}
