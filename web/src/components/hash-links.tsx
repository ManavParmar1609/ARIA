"use client";

import { useEffect } from "react";

/**
 * Links to a place on the same page ("#run", skip links, "Read the report first") move there
 * without a history entry of their own. The browser's own jump would add one the router knows
 * nothing about, and Back from the next page would then change the address but not the page.
 * The address still shows the place, and focus moves to it, as a real jump does.
 */
export function HashLinks() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest("a") : null;
      if (!link || !link.getAttribute("href")?.startsWith("#")) return;
      const target = link.hash
        ? document.getElementById(decodeURIComponent(link.hash.slice(1)))
        : null;
      if (!target) return;
      event.preventDefault();
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      if (!target.matches("a[href], button, input, select, textarea, [tabindex]")) {
        target.setAttribute("tabindex", "-1");
      }
      target.focus({ preventScroll: true });
      // Keep the router's own record of this entry, so Back and Forward still work.
      window.history.replaceState(window.history.state, "", link.hash);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
  return null;
}
