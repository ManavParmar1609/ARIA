import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

export function SiteFooter({ recordedAt, gitSha }: { recordedAt: string; gitSha: string }) {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-10 text-sm text-muted-foreground sm:px-6 md:grid-cols-[1fr_auto] lg:px-8">
        <div className="grid gap-2">
          <Wordmark className="text-foreground" />
          <p>
            Open source under the MIT licence. Logs from Loghub (real, public); incident windows and
            memory are synthetic and labelled so.
          </p>
          <p className="text-xs text-faint">
            Replay recorded {recordedAt.slice(0, 10)} at commit {gitSha}.
          </p>
        </div>
        <nav aria-label="Project links" className="flex flex-wrap items-start gap-x-6 gap-y-2">
          <Link href="/console" className="hover:text-foreground">
            Console
          </Link>
          <a href={REPO_URL} className="hover:text-foreground">
            Source on GitHub
          </a>
          <a href={EVAL_DOC_URL} className="hover:text-foreground">
            Evaluation
          </a>
          <a href={`${REPO_URL}/blob/main/docs/openapi.json`} className="hover:text-foreground">
            API schema
          </a>
        </nav>
      </div>
    </footer>
  );
}
