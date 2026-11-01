"use client";

import { XIcon } from "lucide-react";
import { useRef, type ReactNode } from "react";

import { GLOSSARY, glossaryMentions, type GlossaryKey } from "@/lib/glossary";
import { cx } from "@/lib/cx";

/**
 * A word a newcomer may not know, with its definition one click away: a small card under the
 * word, a dialog named after the term. It is the browser's own popover, so a click outside or
 * Escape closes it and hands focus back to the word. The script moves focus into the card as it
 * opens, so a screen reader reads the definition at once, and closes the card once focus moves
 * past it, so it never covers what Tab reaches next. A browser without CSS anchor positioning
 * opens the card in the middle of the screen instead, over a dimmed page. Each term may appear
 * once per page, or pass a distinct `instance`.
 */
export function Term({
  name,
  instance,
  children,
}: {
  name: GlossaryKey;
  instance?: string;
  children?: ReactNode;
}) {
  const entry = GLOSSARY[name];
  const id = `term-${name}${instance ? `-${instance}` : ""}`;
  // Ties the card to its word for anchor positioning: a dashed ident, so no dots or spaces.
  const anchor = `--${id.replace(/[^\w-]/g, "-")}`;
  // Whether the card is showing, kept from beforetoggle so that closing it never runs twice.
  const open = useRef(false);
  return (
    <>
      <button
        type="button"
        popoverTarget={id}
        aria-haspopup="dialog"
        style={{ anchorName: anchor }}
        className="cursor-help rounded-xs text-inherit underline decoration-primary/70 decoration-dotted underline-offset-[0.2em] transition-colors duration-(--duration-quick) hover:decoration-primary"
      >
        {children ?? entry.term.toLowerCase()}
      </button>
      <span
        id={id}
        popover="auto"
        role="dialog"
        aria-labelledby={`${id}-term`}
        aria-describedby={`${id}-definition`}
        tabIndex={-1}
        style={{ positionAnchor: anchor }}
        onBeforeToggle={(event) => {
          open.current = event.newState === "open";
        }}
        onToggle={(event) => {
          if (event.newState === "open") event.currentTarget.focus();
        }}
        onBlur={(event) => {
          const next = event.relatedTarget;
          if (open.current && next instanceof Node && !event.currentTarget.contains(next)) {
            event.currentTarget.hidePopover();
          }
        }}
        className={cx(
          "w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-rule bg-elevated p-5 text-left text-base font-normal tracking-normal whitespace-normal text-foreground normal-case backdrop:bg-sunken/70",
          // Where the browser anchors it: under the word (above it when there is no room below),
          // clear of the screen's edges, and nothing dims.
          "[position-area:bottom] [position-try-fallbacks:flip-block] supports-[position-area:bottom]:[margin:0.375rem_1rem_0] supports-[position-area:bottom]:backdrop:bg-transparent",
        )}
      >
        <span className="flex items-start justify-between gap-4">
          <span id={`${id}-term`} className="eyebrow block pt-1 text-muted-foreground">
            {entry.term}
          </span>
          <button
            type="button"
            popoverTarget={id}
            popoverTargetAction="hide"
            aria-label="Close"
            className="-mt-1 -mr-2 inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-foreground/8 hover:text-heading"
          >
            <XIcon aria-hidden className="size-4" />
          </button>
        </span>
        <span id={`${id}-definition`} className="mt-3 block leading-relaxed">
          {entry.definition}
        </span>
      </span>
    </>
  );
}

/**
 * Text that comes from data, such as an incident's title or a sample's summary, with the first
 * mention of each glossary word made a Term. `skip` leaves out words already defined nearby;
 * `instance` keeps the ids apart from other copies on the page.
 */
export function TermsIn({
  text,
  instance,
  skip,
}: {
  text: string;
  instance: string;
  skip?: GlossaryKey[];
}) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const { start, end, key } of glossaryMentions(text, skip)) {
    // A line may break on either side of a button, so punctuation touching the word (a quote, a
    // bracket, a comma) is kept on its line with it.
    const before = /[^\s\w]*$/.exec(text.slice(at, start))?.[0] ?? "";
    const after = /^[^\s\w]*/.exec(text.slice(end))?.[0] ?? "";
    parts.push(
      text.slice(at, start - before.length),
      <span key={key} className="whitespace-nowrap">
        {before}
        <Term name={key} instance={instance}>
          {text.slice(start, end)}
        </Term>
        {after}
      </span>,
    );
    at = end + after.length;
  }
  parts.push(text.slice(at));
  return <>{parts}</>;
}
