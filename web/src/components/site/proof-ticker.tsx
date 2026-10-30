"use client";

import { PauseIcon, PlayIcon } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

/**
 * The real data behind the results, as a list that drifts slowly upward on a keylime panel, like
 * the reference's list of services (globals.css: .ticker). It is drawn twice so the loop has no
 * seam; the copy is hidden from assistive technology. Moving content that runs this long needs a
 * way to stop it (WCAG 2.2.2): it pauses while pointed at or focused, and its button stops it.
 * With reduced motion it stands still and scrolls, so it takes keyboard focus (WCAG 2.1.1). The
 * focus ring is drawn on the panel, because the list's fading edges would hide part of it.
 */
export function ProofTicker({ items, seconds = 36 }: { items: string[]; seconds?: number }) {
  const [paused, setPaused] = useState(false);
  // Off screen, it stops too, so a page left at the top can go idle.
  const [onScreen, setOnScreen] = useState(true);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = panel.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(!!entry?.isIntersecting));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const list = (copy: boolean) =>
    items.map((item) => (
      <li
        key={`${copy ? "b" : "a"}-${item}`}
        aria-hidden={copy || undefined}
        className="py-3 text-center font-display text-[1.625rem] leading-tight font-light text-heading sm:text-[1.875rem]"
      >
        {item}
      </li>
    ));
  return (
    <div
      ref={panel}
      className="relative h-full min-h-[20rem] overflow-hidden rounded-card bg-panel-keylime has-[.ticker:focus-visible]:outline-2 has-[.ticker:focus-visible]:outline-offset-2 has-[.ticker:focus-visible]:outline-ring"
    >
      <div
        tabIndex={0}
        role="region"
        aria-label="Data sources"
        className="ticker absolute inset-0 focus-visible:outline-none"
        data-paused={paused || !onScreen || undefined}
      >
        <ul className="ticker-track px-6" style={{ "--ticker-s": `${seconds}s` } as CSSProperties}>
          {list(false)}
          {list(true)}
        </ul>
      </div>
      <button
        type="button"
        onClick={() => setPaused((p) => !p)}
        aria-pressed={paused}
        className="absolute right-3 bottom-3 flex h-8 items-center gap-1.5 rounded-sm bg-raised px-2.5 text-xs font-medium text-heading transition-colors duration-(--duration-quick) hover:bg-sunken motion-reduce:hidden"
      >
        {paused ? (
          <PlayIcon aria-hidden className="size-3.5" />
        ) : (
          <PauseIcon aria-hidden className="size-3.5" />
        )}
        {paused ? "Play" : "Pause"}
        <span className="sr-only"> the list of data sources</span>
      </button>
    </div>
  );
}
