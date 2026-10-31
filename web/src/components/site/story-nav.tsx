"use client";

import { ArrowLeftIcon, ArrowRightIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { STORY_PARTS } from "@/components/site/story-parts";
import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

/** The parts of How ARIA works, numbered in reading order; the one open is filled. */
export function StoryNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Parts of How ARIA works">
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
 * triage of your own. */
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
