import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { ThemeSwitch } from "@/components/theme-switch";
import { Button } from "@/components/ui/button";
import { REPO_URL } from "@/lib/site-data";

const LINKS = [
  { href: "#how", label: "How a run works" },
  { href: "#results", label: "Results" },
  { href: "#standards", label: "Standards" },
];

export function SiteHeader() {
  return (
    <header className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
      <Link href="/" className="rounded-sm" aria-label="ARIA home">
        <Wordmark />
      </Link>
      <nav aria-label="Page sections" className="hidden items-center gap-1 md:flex">
        {LINKS.map((link) => (
          <a
            key={link.href}
            href={link.href}
            className="rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            {link.label}
          </a>
        ))}
        <a
          href={REPO_URL}
          className="rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          GitHub
        </a>
      </nav>
      <div className="flex items-center gap-2">
        <ThemeSwitch />
        <Button asChild variant="primary" size="sm">
          <Link href="/console" prefetch={false}>
            Open the console
          </Link>
        </Button>
      </div>
    </header>
  );
}
