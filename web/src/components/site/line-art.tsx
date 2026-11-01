"use client";

import { useEffect, useRef, type CSSProperties } from "react";

import { cx } from "@/lib/cx";

/*
 * Forest-ink line drawings, as in the reference: many loose lines that run together into one (the
 * logs becoming one incident), the same lines still apart, and rings spreading from a point. They
 * are decorative (aria-hidden). When one scrolls into view its strokes draw in once, each a little
 * after the one before (globals.css: .draw); with reduced motion it is simply there.
 */

const LINES = 9;

/** Where each line starts and how long it is before it bends: uneven, like log lines. */
const START = [52, 18, 70, 6, 40, 0, 62, 26, 46];

function useDrawn<T extends Element>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          el.setAttribute("data-drawn", "");
          observer.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return ref;
}

const stroke = (i: number, len: number) => ({ "--i": i, "--len": len }) as CSSProperties;

/** Lines that run in from the left and merge into one that carries on to the right edge. The
 * caller sets its height: `h-auto` keeps the drawing's shape; a fixed height stretches it (the
 * strokes keep their width). */
export function Converge({ className, apart = false }: { className?: string; apart?: boolean }) {
  const ref = useDrawn<SVGSVGElement>();
  const mid = 120;
  return (
    <svg
      ref={ref}
      viewBox="0 0 1200 240"
      preserveAspectRatio="none"
      className={cx("draw block overflow-visible", className)}
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        {Array.from({ length: LINES }, (_, i) => {
          const y = 40 + i * 20;
          const x0 = START[i] ?? 0;
          const d = apart
            ? `M${x0} ${y}H${560 + ((i * 37) % 90)}`
            : `M${x0} ${y}H640C760 ${y} 820 ${mid} 940 ${mid}`;
          return <path key={i} d={d} vectorEffect="non-scaling-stroke" style={stroke(i, 2400)} />;
        })}
        {apart ? null : (
          <path
            d={`M940 ${mid}H1200`}
            vectorEffect="non-scaling-stroke"
            style={stroke(LINES, 600)}
          />
        )}
      </g>
    </svg>
  );
}
