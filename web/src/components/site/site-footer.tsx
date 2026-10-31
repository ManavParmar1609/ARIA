import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

const DOCS = `${REPO_URL}/blob/main/docs`;
const ADR = `${DOCS}/adr`;

const COLUMNS: { title: string; links: { label: string; href: string; internal?: boolean }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Console", href: "/console", internal: true },
      { label: "Example run", href: "#run" },
      { label: "Real logs", href: "#real" },
      { label: "Questions", href: "#faq" },
    ],
  },
  {
    title: "Evidence",
    links: [
      { label: "Test results", href: EVAL_DOC_URL },
      { label: "Model card", href: `${DOCS}/model-card.md` },
      { label: "Data card", href: `${DOCS}/data-card.md` },
      { label: "Threat model", href: `${DOCS}/threat-model.md` },
    ],
  },
  {
    title: "Build on it",
    links: [
      { label: "Source on GitHub", href: REPO_URL },
      { label: "API schema", href: `${DOCS}/openapi.json` },
      { label: "Design decisions", href: ADR },
      { label: "Back to top", href: "#main" },
    ],
  },
];

const LINK =
  "text-muted-foreground transition-colors duration-(--duration-quick) hover:text-heading";

/** The site's foot: what ARIA is made of, and where to go next. */
export function SiteFooter({ recordedAt, gitSha }: { recordedAt: string; gitSha: string }) {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto grid max-w-[75rem] gap-12 px-4 pt-16 pb-12 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:pt-20">
        <div className="grid max-w-md content-start gap-4">
          <Wordmark />
          <p className="text-muted-foreground">
            Open source under the MIT licence. Measured on real, public logs, tickets and incidents
            (Loghub, a ServiceNow desk, GitLab.com) and on semi-synthetic windows built from real
            lines; every synthetic incident is marked as synthetic.
          </p>
        </div>
        <nav aria-label="Project links" className="grid gap-8 sm:grid-cols-3">
          {COLUMNS.map((column) => (
            <div key={column.title} className="grid content-start gap-3">
              <h2 className="font-sans text-sm font-semibold tracking-[-0.01em] text-heading">
                {column.title}
              </h2>
              <ul className="grid gap-2.5">
                {column.links.map((link) => (
                  <li key={link.label}>
                    {link.internal ? (
                      <Link href={link.href} prefetch={false} className={LINK}>
                        {link.label}
                      </Link>
                    ) : (
                      <a href={link.href} className={LINK}>
                        {link.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </div>
      <div className="mx-auto max-w-[75rem] border-t border-rule px-4 py-6 text-sm text-faint sm:px-6">
        Replay recorded {recordedAt.slice(0, 10)} at commit {gitSha}.
      </div>
    </footer>
  );
}
