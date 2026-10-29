"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether the console's single-key shortcuts ("/", "?", "g" then a letter) are on. They are on by
 * default; WCAG 2.1.4 asks for a way to turn character-key shortcuts off, because speech input
 * and some screen readers type letters that would otherwise trigger them. Ctrl or Cmd + K, which
 * uses a modifier, always works.
 */
const KEY = "aria-shortcuts";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function setShortcutsEnabled(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // Storage can be unavailable (private mode); the choice still holds for this page.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY || event.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useShortcutsEnabled(): boolean {
  return useSyncExternalStore(subscribe, read, () => true);
}

/** True when a key press is meant for a field (typing a "g" must not navigate anywhere). */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** "g" then one of these letters goes to a console page. */
export const GO_KEYS: { key: string; href: string; label: string }[] = [
  { key: "o", href: "/console", label: "Overview" },
  { key: "i", href: "/console/runs", label: "Incidents" },
  { key: "n", href: "/console/runs/new", label: "New triage" },
  { key: "a", href: "/console/ask", label: "Ask ARIA" },
  { key: "m", href: "/console/memory", label: "Incident memory" },
  { key: "r", href: "/console/runbooks", label: "Runbooks" },
  { key: "e", href: "/console/evals", label: "Evaluation" },
  { key: "h", href: "/console/guide", label: "How to use ARIA" },
  { key: "s", href: "/console/settings", label: "Settings" },
];
