"use client";

import { useEffect } from "react";

/**
 * Wakes ARIA's API while the visitor reads the home page (item 31). A free host puts an idle API
 * to sleep, and the first request after that waits for it to start, so asking once in the
 * background means the console is usually awake by the time someone opens it. Nothing is shown,
 * and a failure is ignored: the console says itself when the API is still waking.
 */
export function WakeApi() {
  useEffect(() => {
    const wake = () => {
      fetch("/api/ready", { cache: "no-store" }).catch(() => undefined);
    };
    // After the page has settled, so the request never competes with what the visitor sees.
    // Safari has no requestIdleCallback.
    if (typeof window.requestIdleCallback !== "function") {
      const id = window.setTimeout(wake, 2000);
      return () => window.clearTimeout(id);
    }
    const id = window.requestIdleCallback(wake, { timeout: 4000 });
    return () => window.cancelIdleCallback(id);
  }, []);
  return null;
}
