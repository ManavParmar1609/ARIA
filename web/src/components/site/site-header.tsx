import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { SiteMenu } from "@/components/site/site-menu";
import { REPO_URL } from "@/lib/site-data";

// The same names label the sections themselves, so a link and its destination always match.
export const SECTIONS = [
  { href: "#run", label: "Example run" },
  { href: "#how", label: "How it works" },
  { href: "#results", label: "Results" },
  { href: "#standards", label: "Standards" },
];

const LINK =
  "rounded-sm px-3 py-2 text-base text-foreground transition-colors duration-(--duration-quick) hover:bg-foreground/6 xl:text-lg";

/** A small face in a sky-blue disc: the reference's "chromatic dot" on the console button. */
function Face() {
  return (
    <span
      aria-hidden
      className="grid size-10 shrink-0 place-items-center rounded-full bg-sky transition-transform duration-(--duration-moderate) ease-(--ease-out) group-hover/button:rotate-12"
    >
      <svg viewBox="0 0 24 24" className="size-6">
        <path
          d="M7 10q1.5-2 3 0M14 10q1.5-2 3 0"
          fill="none"
          stroke="#2c2e2a"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        <path d="M7.5 14q4.5 5 9 0Z" fill="#2c2e2a" />
      </svg>
    </span>
  );
}

/**
 * The floating navigation: two white bars on whatever is behind them, as in the reference. The
 * left bar holds the name, the sections and the round menu button; the right one opens the console.
 */
export function SiteHeader() {
  return (
    <header className="fixed inset-x-0 top-3 z-40 px-3 sm:top-4 sm:px-6">
      <div className="mx-auto flex max-w-[75rem] items-stretch gap-2 sm:gap-3">
        <div className="flex h-14 min-w-0 flex-1 items-center justify-between gap-3 rounded-md bg-raised pr-2 pl-4 sm:h-16 sm:pl-5">
          {/* No prefetch: on the home page it would fetch and decode the page already showing. */}
          <Link href="/" prefetch={false} className="rounded-sm" aria-label="ARIA home">
            <Wordmark />
          </Link>
          <nav aria-label="Page sections" className="hidden items-center gap-0.5 lg:flex">
            {SECTIONS.map((link) => (
              <a key={link.href} href={link.href} className={LINK}>
                {link.label}
              </a>
            ))}
            <a href={REPO_URL} className={LINK}>
              GitHub
            </a>
          </nav>
          <SiteMenu links={[...SECTIONS, { href: REPO_URL, label: "GitHub" }]} />
        </div>
        <Link
          href="/console"
          prefetch={false}
          className="group/button flex h-14 shrink-0 items-center gap-3 rounded-md bg-raised pr-2 pl-4 text-base font-medium text-heading transition-colors duration-(--duration-quick) hover:bg-raised/85 sm:h-16 sm:pl-5 sm:text-lg"
        >
          {/* Below 360 px only the face shows; the name stays "Open the console". */}
          <span className="max-[359px]:sr-only">
            <span className="sr-only sm:not-sr-only">Open the </span>
            <span className="capitalize sm:normal-case">console</span>
          </span>
          <Face />
        </Link>
      </div>
    </header>
  );
}
