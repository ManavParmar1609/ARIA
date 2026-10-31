import { ArrowUpRightIcon } from "lucide-react";
import Link from "next/link";

const LINK =
  "inline-flex items-center rounded-sm px-3 py-1.5 text-sm whitespace-nowrap text-charcoal transition-colors duration-(--duration-quick) hover:bg-foreground/6 hover:text-heading dark:text-foreground";

interface NavLink {
  href: string;
  label: string;
}

/** Whether a link leaves the site (the source on GitHub): only those carry the arrow. */
export const leavesSite = (href: string) => /^https?:/.test(href);

/**
 * The home page's links, in plain charcoal: the console pages that explain ARIA, and its source.
 * Below the large breakpoint they move into the menu.
 */
export function SectionNav({ links }: { links: NavLink[] }) {
  return (
    <nav aria-label="Main" className="hidden items-center gap-0.5 lg:flex">
      {links.map((link) =>
        leavesSite(link.href) ? (
          <a key={link.href} href={link.href} className={LINK}>
            {link.label}
            <ArrowUpRightIcon aria-hidden className="ml-1 size-4" />
          </a>
        ) : (
          <Link key={link.href} href={link.href as never} prefetch={false} className={LINK}>
            {link.label}
          </Link>
        ),
      )}
    </nav>
  );
}
