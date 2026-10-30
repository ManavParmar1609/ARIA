import { XIcon } from "lucide-react";
import { type ReactNode } from "react";

import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { cx } from "@/lib/cx";

/**
 * A word a newcomer may not know, with its definition one click away. It uses the browser's
 * own popover (no script), so it works on the landing page without adding to its start-up cost:
 * the button opens the card, and a click outside or Escape closes it. Each term may appear once
 * per page, or pass a distinct `instance`.
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
  return (
    <>
      <button
        type="button"
        popoverTarget={id}
        className="cursor-help rounded-xs text-inherit underline decoration-primary/70 decoration-dotted underline-offset-[0.2em] transition-colors duration-(--duration-quick) hover:decoration-primary"
      >
        {children ?? entry.term.toLowerCase()}
      </button>
      <span
        id={id}
        popover="auto"
        className={cx(
          "m-auto w-[min(26rem,calc(100vw-2rem))] rounded-lg border-0 bg-raised p-6 text-left text-foreground",
          "backdrop:bg-sunken/70",
        )}
      >
        <span className="flex items-start justify-between gap-4">
          <span className="eyebrow block pt-1 text-muted-foreground">{entry.term}</span>
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
        <span className="mt-3 block text-base leading-relaxed">{entry.definition}</span>
      </span>
    </>
  );
}
