import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

const LINK = "transition-colors duration-(--duration-quick) hover:text-heading";

export function SiteFooter({ recordedAt, gitSha }: { recordedAt: string; gitSha: string }) {
  return (
    <footer className="bg-sunken">
      <div className="mx-auto grid max-w-[90rem] gap-10 px-4 py-14 text-sm text-muted-foreground sm:px-6 md:grid-cols-[minmax(0,1fr)_auto] lg:px-8">
        <div className="grid max-w-xl content-start gap-3">
          <Wordmark className="text-heading" />
          <p>
            Open source under the MIT licence. Logs from Loghub (real, public); incident windows and
            memory are synthetic and labelled so.
          </p>
          <p className="text-xs text-faint">
            Replay recorded {recordedAt.slice(0, 10)} at commit {gitSha}.
          </p>
        </div>
        <nav aria-label="Project links" className="grid content-start gap-3">
          <h2 className="eyebrow text-faint">Project</h2>
          <ul className="grid gap-2">
            <li>
              <Link href="/console" prefetch={false} className={LINK}>
                Console
              </Link>
            </li>
            <li>
              <a href={REPO_URL} className={LINK}>
                Source on GitHub
              </a>
            </li>
            <li>
              <a href={EVAL_DOC_URL} className={LINK}>
                Evaluation
              </a>
            </li>
            <li>
              <a href={`${REPO_URL}/blob/main/docs/openapi.json`} className={LINK}>
                API schema
              </a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
