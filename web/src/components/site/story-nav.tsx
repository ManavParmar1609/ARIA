"use client";

import { ArrowLeftIcon, ArrowRightIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { STORY_PARTS } from "@/components/site/story-parts";
import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

/** The heading of the part on show: the first one after the parts' navigation that is laid out
 * (a part kept hidden for Back has no boxes). */
export function partHeading(nav: Element): HTMLElement | null {
  for (const heading of nav.ownerDocument.querySelectorAll<HTMLElement>("h2")) {
    if (!(nav.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    if (heading.getClientRects().length > 0) return heading;
  }
  return null;
}

/**
 * The parts of How ARIA works, numbered in reading order; the one open is filled.
 *
 * Moving to another part (a numbered pill, Next or Previous at the foot, or Back) puts focus on
 * the new part's heading, as a new page would. Otherwise focus stays on the link that was used,
 * out of view at the foot of the page, and the next Tab leaves the part. Arriving on a part, by a
 * link from elsewhere or a reload, leaves focus where the browser puts it.
 */
export function StoryNav() {
  const pathname = usePathname();
  const nav = useRef<HTMLElement>(null);
  const shown = useRef(pathname);
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    const heading = nav.current ? partHeading(nav.current) : null;
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
    heading.focus();
  }, [pathname]);
  return (
    <nav ref={nav} aria-label="Parts of How ARIA works">
      <ol className="flex flex-wrap gap-2">
        {STORY_PARTS.map((part, i) => {
          const current = pathname === part.href;
          return (
            <li key={part.href}>
              <Link
                href={part.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-10 items-center gap-2 rounded-full border py-1 pr-4 pl-1.5 text-sm font-medium transition-colors duration-(--duration-quick)",
                  current
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-rule bg-raised text-heading hover:border-control",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid size-7 place-items-center rounded-full text-xs",
                    current ? "bg-primary-foreground/15" : "bg-panel-sage",
                  )}
                >
                  {i + 1}
                </span>
                {part.label}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Back and next at the foot of each part, so the parts read in order; the last one leads to a
 * triage of your own. Following one moves focus to the new part's heading (StoryNav). */
export function StoryPager() {
  const pathname = usePathname();
  const i = STORY_PARTS.findIndex((part) => part.href === pathname);
  if (i < 0) return null;
  const previous = STORY_PARTS[i - 1];
  const next = STORY_PARTS[i + 1];
  return (
    <nav
      aria-label="Previous and next part"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-6"
    >
      {previous ? (
        <Link href={previous.href} className={buttonVariants({ variant: "raised", size: "md" })}>
          <ArrowLeftIcon aria-hidden />
          {previous.label}
        </Link>
      ) : (
        <span />
      )}
      {next ? (
        <Link href={next.href} className={buttonVariants({ variant: "primary", size: "md" })}>
          Next: {next.label}
          <ArrowRightIcon aria-hidden />
        </Link>
      ) : (
        <Link
          href="/console/runs/new"
          className={buttonVariants({ variant: "primary", size: "md" })}
        >
          Try it on real logs
          <ArrowRightIcon aria-hidden />
        </Link>
      )}
    </nav>
  );
}
