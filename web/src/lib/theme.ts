"use client";

import { useSyncExternalStore } from "react";

import { PREFERS_LIGHT as LIGHT, THEME_KEY as KEY } from "./theme-script";

/**
 * The colour theme: dark by default, light, or whatever the system asks for. The choice lives in
 * localStorage; the page is themed by the `dark` class on <html>, which THEME_SCRIPT (in
 * ./theme-script) sets before first paint. Nothing here touches the page on load, only when the
 * theme changes, so hydration never triggers a full-page style recalculation.
 */
export type ThemeChoice = "dark" | "light" | "system";
export type Theme = "dark" | "light";

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "dark" || value === "light" || value === "system";
}

function stored(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "system" ? value : "dark";
  } catch {
    return "dark";
  }
}

function resolve(choice: ThemeChoice): Theme {
  if (choice !== "system") return choice;
  return window.matchMedia(LIGHT).matches ? "light" : "dark";
}

function apply(theme: Theme): void {
  const root = document.documentElement;
  if (root.classList.contains("dark") === (theme === "dark")) return;
  // Switch every colour at once rather than letting each element's transition run.
  const pause = document.createElement("style");
  pause.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(pause);
  root.classList.toggle("dark", theme === "dark");
  void window.getComputedStyle(root).color;
  window.setTimeout(() => pause.remove(), 0);
}

const listeners = new Set<() => void>();
let detach: (() => void) | undefined;

const emit = () => {
  for (const listener of listeners) listener();
};

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!detach) {
    // Follow changes made in other tabs, and the system's preference when the choice is "system".
    const media = window.matchMedia(LIGHT);
    const sync = () => {
      apply(resolve(stored()));
      emit();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY || event.key === null) sync();
    };
    window.addEventListener("storage", onStorage);
    media.addEventListener("change", sync);
    detach = () => {
      window.removeEventListener("storage", onStorage);
      media.removeEventListener("change", sync);
    };
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      detach?.();
      detach = undefined;
    }
  };
}

const snapshot = () => {
  const choice = stored();
  return `${choice}:${resolve(choice)}`;
};

export function setTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // Storage can be unavailable (private mode); the theme still changes for this page.
  }
  apply(resolve(choice));
  emit();
}

/** The stored choice and the theme it resolves to; both undefined until hydrated. */
export function useTheme(): {
  theme: ThemeChoice | undefined;
  resolvedTheme: Theme | undefined;
  setTheme: (choice: ThemeChoice) => void;
} {
  const value = useSyncExternalStore(subscribe, snapshot, () => null);
  if (value === null) return { theme: undefined, resolvedTheme: undefined, setTheme };
  const [theme, resolvedTheme] = value.split(":") as [ThemeChoice, Theme];
  return { theme, resolvedTheme, setTheme };
}
