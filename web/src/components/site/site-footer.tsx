import Link from "next/link";

import { Wordmark } from "@/components/aria/wordmark";
import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

const LINK =
  "underline decoration-pop-ink/40 underline-offset-4 transition-colors duration-(--duration-quick) hover:decoration-pop-ink";

/** The sunshine band that closes every page of the site: what ARIA is made of, and where to go. */
export function SiteFooter({ recordedAt, gitSha }: { recordedAt: string; gitSha: string }) {
  return (
    // Pulled up under the green panel above it, so its rounded corners show sunshine, not cream.
    <footer className="-mt-[50px] bg-sunshine text-pop-ink">
      <div className="mx-auto grid max-w-[75rem] gap-12 px-4 pt-[calc(4rem+50px)] pb-14 sm:px-6 md:grid-cols-[minmax(0,1fr)_auto] lg:pt-[calc(5rem+50px)]">
        <div className="grid max-w-xl content-start gap-4">
          <Wordmark className="[&_span]:text-pop-ink" />
          <p className="text-lg">
            Open source under the MIT licence. Logs from Loghub (real, public); incident windows and
            memory are synthetic and labelled so.
          </p>
          <p className="text-sm">
            Replay recorded {recordedAt.slice(0, 10)} at commit {gitSha}.
          </p>
        </div>
        <nav aria-label="Project links" className="grid content-start gap-3">
          <h2 className="text-sm font-medium text-pop-ink">Project</h2>
          <ul className="grid gap-2 text-lg">
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
            <li>
              <a href="#main" className={LINK}>
                Back to top
              </a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
