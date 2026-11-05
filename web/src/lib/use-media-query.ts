"use client";

import { useSyncExternalStore } from "react";

/** Whether a media query matches, kept in step with the window; false while rendering on the
 * server, so a layout that depends on it settles on the first paint in the browser. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
