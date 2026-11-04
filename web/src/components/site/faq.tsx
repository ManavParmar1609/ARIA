import Link from "next/link";
import type { ReactNode } from "react";

import { EVAL_DOC_URL, REPO_URL, type TestedOn } from "@/lib/site-data";

/*
 * Questions a first-time visitor asks, set as the reference sets them: the question in the light
 * serif on the left, the answer in the sans on the right, a hairline between rows. Every answer is
 * visible at once, so nothing has to be opened to be read.
 */

const LIMITS = [
  "Most severity labels in the tests come from the rules used to build the test incidents, not from people. The tests on real logs use the labels people gave.",
  "The severity model learned from a dozen public systems. On a system it never saw, its short lists are wider and it asks a person more often; the tests hold each system out in turn to measure that.",
  "The incident library ships with incidents built from samples. Finding similar ones looks easy on it, and will be harder on your own history.",
  "A hosted model makes a triage slower, because it waits for the model's answers. Test results gives the times both ways.",
  "The line filter that catches instructions hidden in logs matches patterns. It is a first defence, not a proof: anything it misses reaches a model only as fenced, untrusted evidence, and a red-team suite measures what such lines can still achieve.",
  "ARIA triages and drafts. It does not fix anything, and it sends nothing without approval.",
];

/** The questions, each answered in plain words; a few answers name only what the results hold. */
function questions(tested: Pick<TestedOn, "unseen" | "tuned">): { q: string; a: ReactNode }[] {
  return [
    {
      q: "Does ARIA ever send a message on its own?",
      a: "No. Messages for Slack, Teams or a status page are drafted and wait for a person to approve, edit or discard them. A draft may link only to allowed sites and address only configured recipients; anything else is taken out before you see it, and listed. Only what you approve goes out, and the decision goes on a record that shows any later change.",
    },
    {
      q: "How does it choose a severity?",
      a: (
        <div className="grid gap-3">
          <p>
            Rules catch known dangerous patterns and set a floor, and to call SEV1 they must show
            two kinds of impact, such as an outage and how far it spreads. A calibrated model turns
            the logs into probabilities and keeps a short list of the levels it can&apos;t rule out
            (a conformal prediction set), with a promise for each level, tighter for SEV1 and SEV2.
            A language model, when there is one, may only pick from that list; without one, ARIA
            takes the most serious level on it and asks a person to confirm.
          </p>
          <p>
            Logs unlike anything the model learned from, and systems it never trained on, always go
            to a person. ARIA also reads the system&apos;s own history: how far errors run above its
            usual rate, and whether reviewers dismissed the same pattern before.
          </p>
          <details className="group text-sm text-muted-foreground">
            <summary className="w-fit cursor-pointer font-medium hover:text-heading">
              How it counts
            </summary>
            <p className="pt-2">
              One message repeated by one server counts as one pattern, not many; a window of
              clients cancelling their own requests counts as noise; and a line with no level counts
              as trouble only beside real errors. The keyword families come from open vocabularies,
              such as gRPC and HTTP status codes and Kubernetes reasons, with their fatal forms
              given floors of their own.
            </p>
          </details>
        </div>
      ),
    },
    {
      q: "What if the logs are unlike anything it has seen?",
      a: `It says so and asks a person. Before deciding, ARIA checks whether the window looks like what its model learned from: one too far from the training data, with too many patterns new to its system, or from a system it never trained on is never decided alone, and the short list widens to what the rules leave open. The tests hold each system out in turn to measure how it does on a new one${tested.unseen ? ", and Test results shows the result" : ""}.`,
    },
    {
      q: "Do I need a model key?",
      a: "No. Offline, every step uses fixed rules and the trained severity model, and the report is written from a template that only states what the evidence shows. With a model key, a language model investigates and writes, and every claim still has to cite its evidence. On this site you can add your own key in Settings. When the site has a key of its own, it serves a pool of models kept inside their own limits, and visitors without a key share it within a daily allowance; when no model has room, the triage is written offline and says when the model is back.",
    },
    {
      q: "What happens to sensitive data in my logs?",
      a: "Secrets and personal data are removed before analysis or any model call, so reports, messages and memory only quote cleaned text. IP and e-mail addresses become stable stand-ins within an incident, and lines that read like instructions to a model are kept out of the analysis; a model sees them only as quoted text it is told not to follow. The lines you send stay with the incident, so it can be replayed, until you delete it or a retention period an operator sets runs out.",
    },
    {
      q: "How does it learn, and how would you know it had gone wrong?",
      a: "From blind checks. In Settings, a person rates a recent incident before seeing ARIA's level, and those ratings recalibrate the short lists one at a time; approvals don't count, because a person approving a report tends to agree with it. Settings also says when a system's mix of levels has shifted beyond chance, an alarm in the logs says when blind checks show more serious incidents rated minor than promised, and every decision is on an append-only record that shows any later change.",
    },
    {
      q: "Does it work with my tools?",
      a: (
        <>
          Alerts from Alertmanager or Grafana start a triage, approved messages go to Slack, Teams
          or any webhook, and other AI agents can hand it work or look things up through open
          protocols (A2A, AG-UI and MCP).{" "}
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
          incidents with labels their owners gave, each scored against a simpler method. The tests
          sit in three rings: fresh samples of the systems ARIA learned from, systems it never saw,
          and real data
          {tested.tuned
            ? ", and each test says whether it was untouched, looked at or tuned on while ARIA was being changed"
            : "; rules and thresholds are chosen on separate validation samples, never on the published tests"}
          . The results, good and bad, are on{" "}
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
}

export function Faq({
  tested = { unseen: false, tuned: false },
}: {
  /** What the published results hold, so an answer never points at a test the page lacks. */
  tested?: Pick<TestedOn, "unseen" | "tuned">;
}) {
  return (
    <div className="grid gap-8">
      <div className="grid max-w-3xl gap-2">
        <h2 id="faq-title" className="text-section">
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
        {questions(tested).map(({ q, a }) => (
          <div
            key={q}
            className="grid gap-2 border-b border-rule py-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12"
          >
            <dt className="font-display text-[1.5rem] leading-snug font-light tracking-[-0.01em] text-balance text-heading sm:text-[1.75rem]">
              {q}
            </dt>
            <dd className="text-base leading-relaxed text-foreground lg:pt-1">{a}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
