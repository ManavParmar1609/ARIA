"use client";

import { useSyncExternalStore } from "react";

// How tightly the incident page sets its evidence and template lists (item 34): comfortable by
// default, compact on request, remembered in this browser only. If storage is blocked (a private
// window), the choice still holds until the page is left.

export type Density = "comfortable" | "compact";

const KEY = "aria.density";
const CHANGED = "aria:density";
let unsaved: Density | null = null;

function read(): Density {
  if (unsaved) return unsaved;
  try {
    return localStorage.getItem(KEY) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function setDensity(density: Density): void {
  try {
    localStorage.setItem(KEY, density);
    unsaved = null;
  } catch {
    unsaved = density;
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function useDensity(): Density {
  return useSyncExternalStore(subscribe, read, () => "comfortable");
}
