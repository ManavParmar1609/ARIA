"use client";

import {
  ArrowDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Clock3Icon,
  PauseIcon,
  PlayIcon,
} from "lucide-react";
import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { LevelChip, SeverityScale } from "@/components/aria/severity";
import type { ShowcaseLine, StepShowcase } from "@/components/site/step-showcase";
import { STEP_LINES } from "@/components/site/step-lines";
import { Button } from "@/components/ui/button";
import { chance } from "@/lib/format";
import { LEVEL_RESPONSE } from "@/lib/levels";
import { cn } from "@/lib/utils";

/*
 * How it works, as a carousel of the four steps (owner request, round 9). Each slide shows its
 * step on the recorded incident. It moves on by itself, slowly; with the pointer resting on it,
 * it slows to a crawl so there is time to read; keyboard focus inside it, the Pause button, a
 * hidden tab or a screen it has scrolled off all stop it. With reduced motion it starts paused
 * and changes slides without moving. Only opacity and transforms animate.
 */

/** How long a slide stays at full speed, and how much slower it runs under a resting pointer. */
const SLIDE_MS = 9000;
const RESTING_SPEED = 0.25;

const REDUCED = "(prefers-reduced-motion: reduce)";

/** Whether the visitor asked for less motion; false while the server renders. */
function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const media = window.matchMedia(REDUCED);
      media.addEventListener("change", changed);
      return () => media.removeEventListener("change", changed);
    },
    () => window.matchMedia(REDUCED).matches,
    () => false,
  );
}

/** "<*>" in a pattern is a slot any value fills: drawn as a small chip. */
function Pattern({ text }: { text: string }) {
  const parts = text.split("<*>");
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 ? (
            <>
              <span
                aria-hidden
                className="mx-0.5 inline-block rounded-[4px] bg-panel-sage px-1 align-baseline font-sans text-[0.75em] leading-[1.4] text-heading"
              >
                any
              </span>
              <span className="sr-only">(any value)</span>
            </>
          ) : null}
        </Fragment>
      ))}
    </>
  );
}

function LogLine({ line }: { line: ShowcaseLine }) {
  return (
    <p
      className={cn(
        "flex items-center gap-3 px-3 py-1",
        line.warn && "bg-sev3/30 dark:bg-sev3/12",
        line.quarantined && "bg-danger/8",
      )}
    >
      <span
        className={cn(
          "tabular w-7 shrink-0 text-right",
          line.warn ? "text-muted-foreground" : "text-faint",
        )}
      >
        {line.lineNo}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          line.quarantined && "text-muted-foreground line-through decoration-danger/60",
        )}
      >
        {line.text}
      </span>
      {line.quarantined ? (
        <span className="shrink-0 rounded-full bg-danger/12 px-2 font-sans text-xs font-medium text-danger">
          Set aside
        </span>
      ) : null}
    </p>
  );
}

/** Step 1: the log as it arrives, and the patterns ARIA groups it into. */
function ReadVisual({ data }: { data: StepShowcase }) {
  return (
    <div className="grid grid-cols-1 gap-2.5">
      <div className="overflow-hidden rounded-[12px] border border-rule bg-raised font-mono text-[0.8125rem] leading-6">
        <p className="flex items-center justify-between gap-3 border-b border-rule bg-sunken px-3 py-1.5 font-sans text-sm text-muted-foreground">
          <span>The log as it arrives ({data.system})</span>
          <span className="tabular">{data.facts.lines} lines</span>
        </p>
        <div className="grid grid-cols-1 py-1">
          {data.lines.map((line) => (
            <LogLine key={line.lineNo} line={line} />
          ))}
        </div>
      </div>
      <div aria-hidden className="flex justify-center text-heading/70">
        <ArrowDownIcon className="size-5" strokeWidth={1.75} />
      </div>
      <ul className="grid grid-cols-1 gap-2" aria-label="The commonest patterns">
        {data.templates.map((t) => (
          <li
            key={t.text}
            className="flex items-center gap-3 rounded-[12px] border border-rule bg-raised px-3 py-2.5"
          >
            <code className="relative min-w-0 flex-1 truncate text-[0.8125rem] text-foreground">
              <Pattern text={t.text} />
            </code>
            {t.novel ? (
              <span className="shrink-0 rounded-full bg-panel-keylime px-2 text-xs font-medium text-heading">
                New
              </span>
            ) : null}
            <span className="tabular shrink-0 text-sm font-medium text-heading">
              {t.count} lines
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Step 2: the level, how likely it is, and the short list the model keeps. */
function RateVisual({ data }: { data: StepShowcase }) {
  const others = data.predictionSet.filter((level) => level !== data.severity);
  return (
    <div className="grid grid-cols-1 gap-5 rounded-[12px] border border-rule bg-raised p-5 sm:p-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <LevelChip severity={data.severity} stamp />
        <span className="text-sm text-muted-foreground">
          {chance(data.facts.probability)} likely
          {others.length ? `; could also be ${others.join(" or ")}` : ""}
        </span>
      </div>
      <SeverityScale
        probabilities={data.probabilities}
        predictionSet={data.predictionSet}
        decided={data.severity}
        setEmpty={data.setEmpty}
        drawBracket
      />
      <p className="border-t border-rule pt-4 text-base leading-relaxed text-foreground">
        {LEVEL_RESPONSE[data.severity]}
      </p>
    </div>
  );
}

/** Step 3: claims from the report, each with the evidence it cites. */
function WriteVisual({ data }: { data: StepShowcase }) {
  return (
    <div className="grid grid-cols-1 gap-4 rounded-[12px] border border-rule bg-raised p-5 sm:p-6">
      <p className="text-sm text-muted-foreground">From the report</p>
      <ul className="grid gap-4">
        {data.claims.map((claim) => (
          <li key={claim.text} className="relative text-base leading-relaxed text-foreground">
            <Pattern text={claim.text} />{" "}
            {claim.evidence.slice(0, 2).map((id) => (
              <span
                key={id}
                className="mr-1 inline-block rounded-full bg-primary px-2 py-0.5 font-mono text-xs text-primary-foreground"
              >
                {id}
              </span>
            ))}
          </li>
        ))}
      </ul>
      <ul className="flex flex-wrap gap-2 border-t border-rule pt-4 text-sm text-heading">
        <li className="rounded-full bg-panel-keylime px-3 py-1">
          {data.facts.toolCalls} checks with tools that can only read
        </li>
        <li className="rounded-full bg-panel-keylime px-3 py-1">
          {data.facts.similar} similar past incidents compared
        </li>
      </ul>
    </div>
  );
}

/** Step 4: the drafted messages, waiting for a person. */
function ReviewVisual({ data }: { data: StepShowcase }) {
  return (
    <div className="grid grid-cols-1 gap-2.5">
      <ul className="grid grid-cols-1 gap-2">
        {data.drafts.map((draft) => (
          <li
            key={draft.title}
            className="grid gap-1.5 rounded-[12px] border border-rule bg-raised px-4 py-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <span className="text-sm font-semibold text-heading">
                {draft.channel} {draft.audience}
              </span>
              <span className="rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                Draft, waiting for approval
              </span>
            </div>
            <p className="line-clamp-2 text-sm leading-relaxed text-foreground">{draft.title}</p>
          </li>
        ))}
      </ul>
      <p className="flex items-center gap-2 px-1 text-base text-heading">
        <Clock3Icon aria-hidden className="size-5 shrink-0" strokeWidth={1.75} />
        Nothing has been sent. A person approves, edits or discards each one.
      </p>
    </div>
  );
}

interface Slide {
  title: string;
  body: string;
  fact: string;
  visual: ReactNode;
}

function slides(data: StepShowcase): Slide[] {
  const f = data.facts;
  const [read, rate, write, review] = STEP_LINES;
  return [
    {
      title: read?.title ?? "",
      body: read?.body ?? "",
      fact: `${f.lines} lines became ${f.templates} patterns; ${f.pseudonyms} addresses swapped for stand-in names; ${f.quarantined} planted line set aside.`,
      visual: <ReadVisual data={data} />,
    },
    {
      title: rate?.title ?? "",
      body: rate?.body ?? "",
      fact: `${data.severity} at ${Math.round(f.probability * 100)}% probability, from rules and a trained model.`,
      visual: <RateVisual data={data} />,
    },
    {
      title: write?.title ?? "",
      body: write?.body ?? "",
      fact: `${f.claims} claims checked against the evidence, ${Math.round(f.coverage * 100)}% of them cited.`,
      visual: <WriteVisual data={data} />,
    },
    {
      title: review?.title ?? "",
      body: review?.body ?? "",
      fact: `${f.actions} messages drafted, ready for review ${f.reviewSeconds} s after the logs arrived.`,
      visual: <ReviewVisual data={data} />,
    },
  ];
}

export function StepCarousel({
  data,
  factLead = "In the example below:",
}: {
  data: StepShowcase;
  /** What the figure under each step is about: the example further down, or elsewhere. */
  factLead?: string;
}) {
  const id = useId();
  const steps = slides(data);
  const count = steps.length;
  const root = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const bars = useRef<(HTMLSpanElement | null)[]>([]);
  const resting = useRef(false);
  const elapsed = useRef(0);
  const [active, setActive] = useState(0);
  // Bumped on each change, so the shown slide's picture plays its entrance again.
  const [shownAt, setShownAt] = useState(0);
  // Reduced motion: nothing moves on its own until the visitor presses Play.
  const reduced = useReducedMotion();
  const [choice, setChoice] = useState<"paused" | "playing" | null>(null);
  const paused = choice ? choice === "paused" : reduced;
  const [onScreen, setOnScreen] = useState(false);
  const [keyboard, setKeyboard] = useState(false);
  const running = !paused && onScreen && !keyboard;

  const show = (next: number) => {
    setActive(((next % count) + count) % count);
    setShownAt((n) => n + 1);
  };

  // Runs only while it can be seen.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(!!entry?.isIntersecting), {
      threshold: 0.35,
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // A new slide starts from the beginning.
  useEffect(() => {
    elapsed.current = 0;
    for (const bar of bars.current) if (bar) bar.style.transform = "scaleX(0)";
  }, [active]);

  useEffect(() => {
    if (!running) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const step = Math.min(now - last, 64);
      last = now;
      if (document.visibilityState === "visible") {
        elapsed.current += step * (resting.current ? RESTING_SPEED : 1);
      }
      const progress = Math.min(1, elapsed.current / SLIDE_MS);
      const bar = bars.current[active];
      if (bar) bar.style.transform = `scaleX(${progress})`;
      if (progress >= 1) {
        setActive((a) => (a + 1) % count);
        setShownAt((n) => n + 1);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, active, count]);

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const moves: Record<string, number> = {
      ArrowRight: i + 1,
      ArrowDown: i + 1,
      ArrowLeft: i - 1,
      ArrowUp: i - 1,
      Home: 0,
      End: count - 1,
    };
    const to = moves[event.key];
    if (to == null) return;
    event.preventDefault();
    const next = ((to % count) + count) % count;
    show(next);
    tabs.current[next]?.focus();
  };

  // Keyboard focus inside stops it until focus leaves; a click doesn't (focus-visible tells).
  const onFocus = (event: FocusEvent<HTMLDivElement>) => {
    if (event.target.matches(":focus-visible")) setKeyboard(true);
  };
  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setKeyboard(false);
  };

  return (
    <div
      ref={root}
      role="region"
      aria-roledescription="carousel"
      aria-label="How ARIA works, step by step"
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") resting.current = true;
      }}
      onPointerLeave={() => {
        resting.current = false;
      }}
      onFocus={onFocus}
      onBlur={onBlur}
      className="grid grid-cols-1 gap-3 rounded-card bg-panel-mint p-3 sm:p-4 lg:p-5"
    >
      <div role="tablist" aria-label="Steps" className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {steps.map((step, i) => {
          const selected = i === active;
          return (
            <button
              key={step.title}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${i}`}
              aria-selected={selected}
              aria-controls={`${id}-slide-${i}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => show(i)}
              onKeyDown={(event) => onTabKey(event, i)}
              className={cn(
                "relative grid min-h-16 grid-cols-[auto_minmax(0,1fr)] items-center gap-3 overflow-hidden rounded-[12px] px-3 py-3 text-left transition-colors duration-(--duration-quick) sm:px-4",
                selected ? "bg-raised" : "hover:bg-raised/55",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "tabular grid size-9 place-items-center rounded-full text-base font-semibold transition-colors duration-(--duration-quick)",
                  selected ? "bg-primary text-primary-foreground" : "bg-panel-sage text-heading",
                )}
              >
                {i + 1}
              </span>
              <span className="text-base leading-snug font-semibold text-heading sm:text-lg">
                {step.title}
              </span>
              <span
                aria-hidden
                className={cn(
                  "absolute inset-x-4 bottom-1.5 h-[3px] overflow-hidden rounded-full bg-heading/10 transition-opacity duration-(--duration-quick)",
                  selected && !paused ? "opacity-100" : "opacity-0",
                )}
              >
                <span
                  ref={(el) => {
                    bars.current[i] = el;
                  }}
                  className="block h-full origin-left scale-x-0 rounded-full bg-primary"
                />
              </span>
            </button>
          );
        })}
      </div>
      {/* The slides share one cell, so the box keeps the tallest one's height and nothing below
          it jumps when a slide changes. */}
      <div
        aria-live={running ? "off" : "polite"}
        className="grid min-w-0 grid-cols-1 rounded-[12px] bg-panel-slate p-5 sm:p-8 lg:p-10"
      >
        {steps.map((step, i) => {
          const shown = i === active;
          return (
            <div
              key={step.title}
              id={`${id}-slide-${i}`}
              role="tabpanel"
              aria-roledescription="slide"
              aria-labelledby={`${id}-tab-${i}`}
              aria-hidden={!shown}
              inert={!shown}
              className={cn(
                "grid min-w-0 grid-cols-1 content-start gap-8 [grid-area:1/1] motion-safe:transition-[opacity,translate] motion-safe:duration-(--duration-slow) motion-safe:ease-(--ease-out) lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12",
                shown ? "opacity-100" : "pointer-events-none translate-y-2 opacity-0",
              )}
            >
              <div className="grid min-w-0 content-start gap-4">
                <p className="tabular text-sm font-medium text-heading/80">
                  Step {i + 1} of {count}
                </p>
                <h3 className="text-2xl leading-snug sm:text-3xl">{step.title}</h3>
                <p className="text-lg leading-relaxed text-heading/85">{step.body}</p>
                <p className="mt-2 border-t border-heading/15 pt-4 text-base leading-relaxed text-heading/85">
                  <span className="font-semibold text-heading">{factLead} </span>
                  {step.fact}
                </p>
              </div>
              <div key={shown ? `on-${shownAt}` : "off"} className="min-w-0">
                {step.visual}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-1 pt-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="raised"
            size="md"
            onClick={() => setChoice(paused ? "playing" : "paused")}
            aria-label={paused ? "Play: move through the steps" : "Pause: stay on this step"}
          >
            {paused ? (
              <PlayIcon aria-hidden className="size-4" strokeWidth={2} />
            ) : (
              <PauseIcon aria-hidden className="size-4" strokeWidth={2} />
            )}
            {paused ? "Play" : "Pause"}
          </Button>
          <Button
            variant="raised"
            size="icon"
            onClick={() => show(active - 1)}
            aria-label="Previous step"
          >
            <ChevronLeftIcon aria-hidden className="size-5" strokeWidth={1.75} />
          </Button>
          <Button
            variant="raised"
            size="icon"
            onClick={() => show(active + 1)}
            aria-label="Next step"
          >
            <ChevronRightIcon aria-hidden className="size-5" strokeWidth={1.75} />
          </Button>
        </div>
        <p className="text-sm text-heading/80">
          {paused
            ? "Paused. Choose a step, or press Play."
            : "Moves on by itself, and slows down while your pointer rests on it."}
        </p>
      </div>
    </div>
  );
}
