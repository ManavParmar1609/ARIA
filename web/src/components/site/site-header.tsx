import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { SectionNav } from "@/components/site/section-nav";
import { SiteMenu } from "@/components/site/site-menu";
import { ThemeSwitch } from "@/components/theme-switch";
import { ArrowCircle } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { REPO_URL } from "@/lib/site-data";

// The home page is short; the explanation and the evidence live in the console's pages, and each
// link names the page it opens.
export const SECTIONS = [
  { href: "/console/how-it-works", label: "How it works" },
  { href: "/console/how-it-works/example", label: "Example" },
  { href: "/console/evals", label: "Test results" },
  { href: "/console/how-it-works/questions", label: "Questions" },
];

/**
 * The navigation: the name on the left, the pages that explain ARIA in plain charcoal, and the
 * console as the action on the right. Below the large breakpoint the links and the theme move
 * into a menu.
 */
export function SiteHeader() {
  const links = [...SECTIONS, { href: REPO_URL, label: "GitHub" }];
  return (
    <header data-fixed-header className="fixed inset-x-0 top-0 z-40 bg-background">
      <div className="mx-auto flex h-16 max-w-[75rem] items-center justify-between gap-3 px-3 sm:px-6">
        {/* No prefetch: on the home page it would fetch and decode the page already showing. */}
        <Link href="/" prefetch={false} className="rounded-sm" aria-label="ARIA home">
          <Wordmark />
        </Link>
        <SectionNav links={links} />
        <div className="flex items-center gap-2">
          <Link
            href="/console"
            prefetch={false}
            // A cream button with a hairline: the hero's "Try it" is the page's one main action.
            className={buttonVariants({ variant: "raised", size: "md" })}
          >
            {/* "Console" on a phone; a screen reader always hears "Open the console". */}
            <span>
              <span className="sr-only sm:not-sr-only">Open the </span>
              <span className="capitalize sm:normal-case">console</span>
            </span>
            <ArrowCircle size="sm" />
          </Link>
          {/* On a wide screen the sections are already in view, so only the theme needs a place;
              below that, one menu holds both. */}
          <span className="hidden lg:inline-flex">
            <ThemeSwitch className="text-heading" />
          </span>
          <div className="lg:hidden">
            <SiteMenu links={links} />
          </div>
        </div>
      </div>
    </header>
  );
}
