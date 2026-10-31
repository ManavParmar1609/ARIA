import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";

import { Closing } from "@/components/site/closing";
import { Hero } from "@/components/site/hero";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { STEP_LINES } from "@/components/site/step-lines";
import { WakeApi } from "@/components/site/wake-api";
import { replay } from "@/lib/site-data";

// The home page says what ARIA is and lets a visitor try it: the headline with a real report, the
// proof, the four steps in a line each, and the way in. The whole story (the recorded incident,
// the steps in detail, the test results and the questions) is the console's How ARIA works page,
// so this page stays short (owner feedback, round 8).

/** The four steps, one line each, and the way to the full explanation. */
function FourSteps() {
  return (
    <section
      id="how"
      aria-labelledby="how-title"
      className="mx-auto grid max-w-[75rem] scroll-mt-20 gap-8 px-3 py-16 sm:px-6 lg:py-20"
    >
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <h2 id="how-title" className="text-section max-w-[22ch]">
          How it works, in four steps
        </h2>
        <Link
          href="/console/how-it-works"
          prefetch={false}
          className="inline-flex items-center gap-1.5 text-lg font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
        >
          See how ARIA works, with a real example
          <ArrowRightIcon aria-hidden className="size-5" />
        </Link>
      </div>
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {STEP_LINES.map((step, i) => (
          <li
            key={step.title}
            className="grid content-start gap-3 rounded-card border border-rule bg-raised p-6"
          >
            <span
              aria-hidden
              className="grid size-9 place-items-center rounded-full bg-panel-sage text-base font-medium text-heading"
            >
              {i + 1}
            </span>
            <h3 className="font-sans text-lg font-medium text-heading">{step.title}</h3>
            <p className="text-base leading-relaxed text-muted-foreground">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Landing() {
  const data = replay();
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <SiteHeader />
      <WakeApi />
      <main id="main">
        <Hero data={data} />
        <FourSteps />
        <Closing />
      </main>
      <SiteFooter recordedAt={data.recordedAt} />
    </>
  );
}
