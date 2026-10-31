import Link from "next/link";
import type { ReactNode } from "react";

import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

/*
 * Questions a first-time visitor asks, set as the reference sets them: the question in the light
 * serif on the left, the answer in the sans on the right, a hairline between rows. Every answer is
 * visible at once, so nothing has to be opened to be read.
 */

const LIMITS = [
  "Most severity labels in the tests come from the rules used to build the test incidents, not from people. The tests on real logs use the labels people gave.",
  "The incident library ships with incidents built from samples. Finding similar ones looks easy on it, and will be harder on your own history.",
  "A hosted model makes a triage slower, because it waits for the model's answers. Test results gives the times both ways.",
  "The line filter that catches instructions hidden in logs matches patterns. It is a first defence, not a proof: anything it misses reaches a model only as fenced, untrusted evidence.",
  "ARIA triages and drafts. It does not fix anything, and it sends nothing without approval.",
];

const QUESTIONS: { q: string; a: ReactNode }[] = [
  {
    q: "Does ARIA ever send a message on its own?",
    a: "No. Messages for Slack, Teams or a status page are drafted and wait for a person to approve, edit or discard them. Only what they approve goes out, and the incident keeps a note of who decided and when.",
  },
  {
    q: "How does it choose a severity?",
    a: "Rules catch known dangerous patterns and set a floor. A calibrated model turns the logs into probabilities and keeps a short list of the levels it can't rule out (a conformal prediction set). A language model, when there is one, may only pick from that list; without one, ARIA takes the most serious level on it and asks a person to confirm.",
  },
  {
    q: "Do I need a model key?",
    a: "No. Offline, every step uses fixed rules and the trained severity model, and the report is written from a template that only states what the evidence shows. With a model key, a language model investigates and writes, and every claim still has to cite its evidence. On this site you can add your own key in Settings, and when the site has a key of its own, visitors without one share it within a daily allowance.",
  },
  {
    q: "What happens to sensitive data in my logs?",
    a: "Secrets and personal data are removed before analysis or any model call, so reports, messages and memory only quote cleaned text. IP and e-mail addresses become stable stand-ins within an incident, and lines that read like instructions to a model are set aside and shown to it only as fenced evidence. The lines you send stay with the incident, so it can be replayed, until you delete it.",
  },
  {
    q: "Does it work with my tools?",
    a: (
      <>
        Alerts from Alertmanager or Grafana start a triage, approved messages go to Slack, Teams or
        any webhook, and other AI agents can hand it work or look things up through open protocols
        (A2A, AG-UI and MCP).{" "}
        <Link href="/console/guide/connect" prefetch={false} className="link">
          How to connect each one
        </Link>
        .
      </>
    ),
  },
  {
    q: "How do you know it works?",
    a: (
      <>
        Every test result on this site comes from a published test: public logs, tickets and
        incidents with labels their owners gave, each scored against a simpler method. The results,
        good and bad, are on{" "}
        <Link href="/console/evals" prefetch={false} className="link">
          Test results
        </Link>
        , and the method is in{" "}
        <a href={EVAL_DOC_URL} className="link">
          the evaluation report
        </a>
        .
      </>
    ),
  },
  {
    q: "Where does it fall short?",
    a: (
      <ul className="grid gap-2">
        {LIMITS.map((item) => (
          <li key={item} className="grid grid-cols-[0.75rem_1fr] gap-2.5">
            <span aria-hidden className="mt-[0.6rem] block size-1.5 rounded-full bg-primary" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    ),
  },
];

export function Faq() {
  return (
    <div className="grid gap-10">
      <div className="grid max-w-3xl gap-3">
        <span className="tag justify-self-start">Questions</span>
        <h2 id="faq-title" className="text-display">
          What people ask first
        </h2>
        <p className="text-lead">
          Something else?{" "}
          <a href={`${REPO_URL}/issues`} className="link">
            Ask on GitHub
          </a>
          .
        </p>
      </div>
      <dl className="border-t border-rule">
        {QUESTIONS.map(({ q, a }) => (
          <div
            key={q}
            className="grid gap-3 border-b border-rule py-8 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-16 lg:py-10"
          >
            <dt className="font-display text-[1.75rem] leading-[1.25] font-light tracking-[-0.01em] text-heading sm:text-[2.125rem]">
              {q}
            </dt>
            <dd className="text-[0.9375rem] leading-relaxed text-foreground lg:pt-2">{a}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
