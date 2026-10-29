import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { SiteMenu } from "@/components/site/site-menu";
import { ThemeSwitch } from "@/components/theme-switch";
import { Button } from "@/components/ui/button";
import { REPO_URL } from "@/lib/site-data";

// The same names label the sections themselves, so a link and its destination always match.
export const SECTIONS = [
  { href: "#run", label: "Example run" },
  { href: "#how", label: "How it works" },
  { href: "#results", label: "Results" },
  { href: "#standards", label: "Standards" },
];

const LINK =
  "eyebrow rounded-sm px-3 py-2 text-muted-foreground transition-colors duration-(--duration-quick) hover:text-heading";

export function SiteHeader() {
  return (
    <header className="relative z-20 mx-auto flex h-20 w-full max-w-[90rem] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
      <Link href="/" className="rounded-sm text-heading" aria-label="ARIA home">
        <Wordmark />
      </Link>
      <nav aria-label="Page sections" className="hidden items-center gap-1 lg:flex">
        {SECTIONS.map((link) => (
          <a key={link.href} href={link.href} className={LINK}>
            {link.label}
          </a>
        ))}
        <a href={REPO_URL} className={LINK}>
          GitHub
        </a>
      </nav>
      <div className="flex items-center gap-2">
        <SiteMenu links={[...SECTIONS, { href: REPO_URL, label: "GitHub" }]} />
        <ThemeSwitch />
        <Button asChild variant="secondary" size="sm" className="eyebrow">
          <Link href="/console" prefetch={false}>
            Console
          </Link>
        </Button>
      </div>
    </header>
  );
}
