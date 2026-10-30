import { ArrowRightIcon, BellRingIcon, CheckIcon } from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import type { Replay } from "@/lib/site-data";
import { cn } from "@/lib/utils";

const SEVERITIES = ["SEV1", "SEV2", "SEV3", "SEV4"] as const;

/** A cream card on the slate panel, with its small name below it, as the reference sets them. */
function Card({ name, delay, children }: { name: string; delay: number; children: ReactNode }) {
  return (
    <div
      className="hero-rise grid content-start justify-items-center gap-3"
      style={{ "--d": `${delay}ms` } as CSSProperties}
    >
      <div className="grid w-full content-start gap-3 rounded-[12px] bg-raised p-4 sm:min-h-[15.5rem] lg:p-5">
        {children}
      </div>
      <span className="rounded-full bg-raised px-3 py-0.5 text-xs font-medium text-heading">
        {name}
      </span>
    </div>
  );
}

/** The recorded run in three cards: the alert, its severity, and the report waiting for review. */
function Trio({ data }: { data: Replay }) {
  // The first claim that reads as plain English: one quoting a log template ("<*>") would be cut
  // mid-quote by the card's line clamp.
  const index = Math.max(
    0,
    data.claims.findIndex((c) => !c.text.includes("<*>")),
  );
  const claim = data.claims[index];
  const p = Math.round((data.probabilities[data.severity] ?? 0) * 100);
  const summary = `From a recorded run: ${data.title}, ${data.nLines} log lines, rated ${data.severity} at ${p}% and waiting for a person to approve the report.`;
  return (
    <figure aria-label={summary} className="relative">
      {/* A thin thread through the cards, as in the reference. */}
      <div
        aria-hidden
        className="hero-thread absolute inset-x-[8%] top-[42%] hidden h-px bg-forest/25 sm:block dark:bg-foreground/20"
      />
      <div aria-hidden className="relative grid gap-4 sm:grid-cols-3 sm:gap-3 lg:gap-5">
        <Card name="Alert" delay={100}>
          <span className="grid size-11 place-items-center rounded-full bg-panel-keylime text-heading">
            <BellRingIcon className="size-5" strokeWidth={1.5} />
          </span>
          <p className="font-display text-[1.375rem] leading-tight font-light tracking-[-0.01em] text-heading">
            {data.title}
          </p>
          <p className="text-xs text-muted-foreground">
            {data.system}, {data.nLines} lines over {Math.round(data.windowMinutes)} minutes
          </p>
          <span className="inline-flex items-center gap-1.5 justify-self-start rounded-full bg-panel-keylime px-2.5 py-1 text-xs font-medium text-heading">
            <CheckIcon className="size-3.5" strokeWidth={2} />
            Triaged
          </span>
        </Card>
        <Card name="Severity" delay={240}>
          <p className="font-display text-[1.375rem] leading-none font-light text-heading">
            {data.severity}
            <span className="ml-2 font-sans text-xs text-muted-foreground">{p}% likely</span>
          </p>
          <ul className="grid gap-2">
            {SEVERITIES.map((sev) => {
              const share = data.probabilities[sev] ?? 0;
              const inSet = data.predictionSet.includes(sev);
              return (
                <li key={sev} className="grid grid-cols-[2.5rem_1fr] items-center gap-2 text-xs">
                  <span className={inSet ? "font-semibold text-heading" : "text-muted-foreground"}>
                    {sev}
                  </span>
                  <span className="h-2 rounded-full bg-sunken">
                    <span
                      className={cn(
                        "block h-full rounded-full",
                        inSet ? "bg-primary" : "bg-panel-sage",
                      )}
                      style={{ width: `${Math.max(4, Math.round(share * 100))}%` }}
                    />
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-muted-foreground">
            Prediction set: {data.predictionSet.join(" or ")}
          </p>
        </Card>
        <Card name="Report" delay={380}>
          <p className="text-xs font-medium text-muted-foreground">
            Claim {index + 1} of {data.claims.length}
          </p>
          <p className="line-clamp-4 text-sm leading-snug text-foreground">{claim?.text}</p>
          <div className="flex flex-wrap gap-1.5">
            {(claim?.evidence ?? []).slice(0, 3).map((id) => (
              <span
                key={id}
                className="rounded-full bg-panel-mint px-2 py-0.5 font-mono text-[0.6875rem] text-heading"
              >
                {id}
              </span>
            ))}
          </div>
          <div className="mt-1 flex gap-1.5">
            <span className="rounded-[7px] bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground">
              Approve
            </span>
            <span className="rounded-[7px] bg-foreground/6 px-2.5 py-1 text-xs font-medium text-heading">
              Edit
            </span>
          </div>
        </Card>
      </div>
    </figure>
  );
}

/** The first screen: the promise on sage, the main action beneath it, the product on slate. */
export function Hero({ data }: { data: Replay }) {
  return (
    <section
      aria-labelledby="hero-title"
      className="mx-auto grid max-w-[75rem] gap-3 px-3 pt-20 sm:px-6 sm:pt-24 lg:grid-cols-[minmax(0,11fr)_minmax(0,13fr)]"
    >
      <div className="grid grid-rows-[1fr_auto] gap-3">
        <div className="flex flex-col rounded-card bg-panel-sage p-7 sm:p-10">
          <h1 id="hero-title" className="text-hero max-w-[12ch]">
            Incident triage that shows its work.
          </h1>
          <p className="mt-10 max-w-[44ch] text-[0.9375rem] leading-relaxed text-heading lg:mt-auto lg:pt-16">
            ARIA reads the alert and its logs, rates severity with calibrated confidence and drafts
            a report in which every claim cites its evidence. Nothing is sent until a person
            approves.
          </p>
        </div>
        <Link
          href="/console"
          prefetch={false}
          className="group/button flex h-16 items-center justify-between rounded-card bg-primary px-7 text-[0.9375rem] font-medium text-primary-foreground transition-colors duration-(--duration-quick) hover:bg-primary-hover sm:h-[4.75rem]"
        >
          Open the console
          <ArrowRightIcon
            aria-hidden
            strokeWidth={1.5}
            className="size-6 transition-transform duration-(--duration-moderate) ease-(--ease-out) group-hover/button:translate-x-1"
          />
        </Link>
      </div>
      <div className="grid content-center rounded-card bg-panel-slate p-5 sm:p-8 lg:p-10">
        <Trio data={data} />
      </div>
    </section>
  );
}
