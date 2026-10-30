"use client";

import { ArrowUpRightIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

const LINK =
  "relative z-10 rounded-sm px-3 py-1.5 text-sm whitespace-nowrap text-charcoal transition-colors duration-(--duration-quick) hover:text-heading aria-[current=true]:text-heading dark:text-foreground";

interface NavLink {
  href: string;
  label: string;
}

/**
 * The landing page's section links. A keylime pill glides to the link of the section being read:
 * the one crossing a thin band just above the middle of the screen. Above the first section (the
 * hero) no link is current and the pill is hidden.
 */
export function SectionNav({ links }: { links: NavLink[] }) {
  const nav = useRef<HTMLElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    const ids = links.map((link) => link.href).filter((href) => href.startsWith("#"));
    const crossing = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = `#${entry.target.id}`;
          if (entry.isIntersecting) crossing.add(id);
          else crossing.delete(id);
        }
        setCurrent(ids.filter((id) => crossing.has(id)).at(-1) ?? null);
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    for (const id of ids) {
      const section = document.getElementById(id.slice(1));
      if (section) observer.observe(section);
    }
    return () => observer.disconnect();
  }, [links]);

  // Move the pill under the current link (FLIP: it takes its new size at once, starts drawn where
  // it was with a transform, and eases to the link, so only transform and opacity animate). It
  // re-measures without animating when the links change size at a breakpoint.
  const last = useRef<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    const el = pill.current;
    const root = nav.current;
    if (!el || !root) return;
    const place = (animate: boolean) => {
      const link = current ? root.querySelector<HTMLAnchorElement>(`a[href="${current}"]`) : null;
      if (!link) {
        el.style.opacity = "0";
        last.current = null;
        return;
      }
      const [x, y, w] = [link.offsetLeft, link.offsetTop, link.offsetWidth];
      const from = animate ? last.current : null;
      el.style.width = `${w}px`;
      el.style.height = `${link.offsetHeight}px`;
      el.style.transition = "none";
      el.style.transform = from
        ? `translate(${from.x}px, ${y}px) scaleX(${from.w / w})`
        : `translate(${x}px, ${y}px)`;
      void el.offsetWidth;
      el.style.transition = "";
      el.style.transform = `translate(${x}px, ${y}px)`;
      el.style.opacity = "1";
      last.current = { x, w };
    };
    place(true);
    // ResizeObserver also reports once on observe; only a real change of width re-places.
    let width = root.offsetWidth;
    const resize = new ResizeObserver(() => {
      if (root.offsetWidth === width) return;
      width = root.offsetWidth;
      place(false);
    });
    resize.observe(root);
    return () => resize.disconnect();
  }, [current]);

  return (
    <nav
      ref={nav}
      aria-label="Page sections"
      className="relative hidden items-center gap-0.5 lg:flex"
    >
      <span
        ref={pill}
        aria-hidden
        className="absolute top-0 left-0 origin-left rounded-sm bg-panel-keylime opacity-0 transition-[transform,opacity] duration-(--duration-slow) ease-(--ease-out)"
      />
      {links.map((link) => (
        <a
          key={link.href}
          href={link.href}
          aria-current={link.href === current ? "true" : undefined}
          className={LINK}
        >
          {link.label}
          {/* The source leaves the page; every other link stays on it. */}
          {link.href.startsWith("#") ? null : (
            <ArrowUpRightIcon aria-hidden className="ml-1 inline size-4 align-[-2px]" />
          )}
        </a>
      ))}
    </nav>
  );
}
