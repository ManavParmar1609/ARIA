import type { ReactNode } from "react";

import { EVAL_DOC_URL, REPO_URL } from "@/lib/site-data";

/*
 * Questions a first-time visitor asks, set as the reference sets them: the question in the light
 * serif on the left, the answer in the sans on the right, a hairline between rows. Every answer is
 * visible at once, so nothing has to be opened to be read.
 */

const LIMITS = [
  "Severity labels for most windows come from the scenario generator, not from people. The real-log results above use labels people gave.",
  "Incident memory ships synthetic. Retrieval looks perfect on it and will not on your own history.",
  "With a hosted model a run takes minutes. The fast numbers on this page are the offline path.",
  "The injection guard matches patterns. It is a first line of defence, not a proof: anything it misses reaches a model only as fenced, untrusted evidence.",
  "ARIA triages and drafts. It does not remediate, and it sends nothing without approval.",
];

const QUESTIONS: { q: string; a: ReactNode }[] = [
  {
    q: "Does ARIA ever send a message on its own?",
    a: "No. Messages for Slack, Teams or a status page are drafted and wait for a person to approve, edit or reject them. Only what they approve goes out, and the run keeps a record of who decided.",
  },
  {
    q: "How does it choose a severity?",
    a: "Rules catch known dangerous patterns and set a floor. A calibrated model turns the window into probabilities, and conformal prediction keeps the severities it cannot rule out. A language model, when one is set up, may only pick inside that set; without one, ARIA takes the most severe level in it and asks for a review.",
  },
  {
    q: "Can I run it without an API key?",
    a: "Yes. Offline, every step uses deterministic logic and the trained severity model, and the report is written from a grounded template. Add a Gemini or NVIDIA NIM key, Azure OpenAI or any OpenAI-compatible endpoint when you want a language model to investigate and write.",
  },
  {
    q: "What happens to sensitive data in my logs?",
    a: "Secrets and personal data are redacted before analysis, storage or any model call. IP and e-mail addresses become stable pseudonyms within a run, and lines that read like instructions to a model are quarantined and shown to it only as fenced evidence.",
  },
  {
    q: "How do you know it works?",
    a: (
      <>
        Every number on this page comes from the same evaluation run, on public logs, tickets and
        incidents with labels their owners gave, each scored against simpler baselines. The method
        and the results, good and bad, are in{" "}
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
