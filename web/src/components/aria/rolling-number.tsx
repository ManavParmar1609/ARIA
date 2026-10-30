"use client";

import { useEffect, useRef, type CSSProperties } from "react";

const DIGITS = "0123456789";

/**
 * A number whose digits roll up when it scrolls into view, like an odometer.
 *
 * The server draws each digit as a strip already showing its final digit, so the first paint,
 * no-script views and screen readers (which read the plain text beside it) get the real value. A
 * number still below the screen once the page has loaded is reset to zeros out of sight and rolls
 * up when it comes into view, then rests with crisp edges. Under reduced motion it never moves.
 * Only transforms animate.
 */
export function RollingNumber({ value }: { value: string }) {
  const root = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // The observer's first report says where the number is, without forcing a layout during
    // hydration: one already on (or above) the screen keeps its digits; one below waits at zero.
    let first = true;
    let rest = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (first) {
          first = false;
          const bottom = entry.rootBounds?.height ?? window.innerHeight;
          if (entry.boundingClientRect.top < bottom) {
            observer.disconnect();
            return;
          }
          el.dataset.roll = "ready";
          return;
        }
        if (!entry.isIntersecting) return;
        el.dataset.roll = "go";
        observer.disconnect();
        // Once the last column has landed (1.1 s, 70 ms later per digit), it rests.
        const columns = el.querySelectorAll(".roll-col").length;
        rest = window.setTimeout(() => (el.dataset.roll = "done"), 1200 + 70 * columns);
      },
      { threshold: 0.6 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      window.clearTimeout(rest);
    };
  }, []);

  const chars = [...value];
  // Each digit's place among the digits, so the columns start rolling one after another.
  const place = chars.map((_, i) => chars.slice(0, i).filter((c) => DIGITS.includes(c)).length);
  // Words keep real spaces between them, so a value wraps where its plain text would.
  const words = value.split(/( )/);
  const starts = words.map((_, w) => words.slice(0, w).join("").length);
  return (
    <span ref={root} className="roll">
      <span className="sr-only">{value}</span>
      <span aria-hidden className="roll-face">
        {words.map((word, w) =>
          word === " " ? (
            " "
          ) : (
            <span key={w} className="roll-word">
              {[...word].map((char, j) => {
                const at = DIGITS.indexOf(char);
                if (at < 0) {
                  return (
                    <span key={j} className="roll-char">
                      {char}
                    </span>
                  );
                }
                const style = {
                  "--roll-to": at,
                  "--roll-i": place[(starts[w] ?? 0) + j],
                } as CSSProperties;
                return (
                  <span key={j} className="roll-col">
                    <span className="roll-strip" style={style}>
                      {[...DIGITS].map((d) => (
                        <span key={d}>{d}</span>
                      ))}
                    </span>
                  </span>
                );
              })}
            </span>
          ),
        )}
      </span>
    </span>
  );
}
