import Link from "next/link";
import type { ComponentType } from "react";

import {
  ApproveScene,
  EvidenceScene,
  NoiseScene,
  StampScene,
} from "@/components/illustrations/scenes";
import { ArrowCircle, Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Tone = "coral" | "sunshine" | "sky" | "lilac";

interface Chapter {
  title: string;
  body: string;
  cta: { label: string; href: string };
  tone: Tone;
  Scene: ComponentType<{ className?: string }>;
}

// What ARIA does, in the order a run does it. Each card's button leads to where the page shows it.
const CHAPTERS: Chapter[] = [
  {
    title: "From noise to a signal.",
    body: "Thousands of log lines become a handful of templates. E-mail and IP addresses are pseudonymised, and any line that reads like an instruction to a model is quarantined before anything else reads it.",
    cta: { label: "See the logs it read", href: "#run" },
    tone: "coral",
    Scene: NoiseScene,
  },
  {
    title: "A severity you can check.",
    body: "Rules and a calibrated model rate the incident, and conformal prediction says which severities are still plausible. When ARIA is unsure it takes the more severe one and asks a person to look.",
    cta: { label: "How severity is decided", href: "#how" },
    tone: "sunshine",
    Scene: StampScene,
  },
  {
    title: "Every claim shows its evidence.",
    body: "An investigator tests hypotheses with read-only tools, and the report may only say what that evidence supports. A validator rejects any claim whose citation is missing.",
    cta: { label: "Try a citation", href: "#run" },
    tone: "sky",
    Scene: EvidenceScene,
  },
  {
    title: "Nothing goes out without you.",
    body: "The run pauses for review. Approve, edit or reject: only the messages you tick are sent, and the approved incident joins memory, so the next similar alert finds it.",
    cta: { label: "Open the console", href: "/console" },
    tone: "lilac",
    Scene: ApproveScene,
  },
];

/**
 * ARIA's story in four chapters along a winding green road, after the reference's scrolling path.
 * The road is one stroke that stretches with the section's height, so it never needs measuring.
 */
export function Story() {
  return (
    <div className="relative">
      <svg
        aria-hidden
        focusable="false"
        viewBox="0 0 1200 2400"
        preserveAspectRatio="none"
        className="pointer-events-none absolute inset-0 -z-10 hidden h-full w-full md:block"
      >
        <path
          d="M930 -40C930 260 300 300 290 620C280 920 910 900 920 1220C930 1520 290 1500 290 1820C290 2080 600 2140 600 2440"
          fill="none"
          stroke="var(--grass)"
          strokeWidth="150"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <ol className="grid gap-16 md:gap-10">
        {CHAPTERS.map((chapter, i) => {
          const flip = i % 2 === 1;
          return (
            <li
              key={chapter.title}
              className="grid items-center gap-6 md:min-h-[34rem] md:grid-cols-2 md:gap-10"
            >
              <chapter.Scene
                className={cn("mx-auto h-auto w-full max-w-md md:max-w-none", flip && "md:order-2")}
              />
              <article className="grid min-w-0 content-start gap-5 rounded-lg bg-raised p-7 sm:p-10 lg:p-12">
                <h3 className="text-3xl leading-[1.05] tracking-heading sm:text-4xl">
                  {chapter.title}
                </h3>
                <p className="text-lg leading-snug text-foreground sm:text-xl">{chapter.body}</p>
                {/* The label may wrap on a narrow phone rather than push the card wider. */}
                <Button
                  asChild
                  variant={chapter.tone}
                  size="lg"
                  className="h-auto min-h-14 justify-self-start py-2 pr-2 text-left whitespace-normal"
                >
                  {chapter.cta.href.startsWith("/") ? (
                    <Link href={chapter.cta.href} prefetch={false}>
                      {chapter.cta.label}
                      <ArrowCircle tone="white" />
                    </Link>
                  ) : (
                    <a href={chapter.cta.href}>
                      {chapter.cta.label}
                      <ArrowCircle tone="white" />
                    </a>
                  )}
                </Button>
              </article>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
