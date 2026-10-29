import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setTheme, useTheme } from "./theme";
import { THEME_SCRIPT } from "./theme-script";

const root = document.documentElement;

afterEach(() => {
  localStorage.clear();
  root.className = "";
});

describe("theme", () => {
  it("applies a stored light theme before first paint", () => {
    root.classList.add("dark");
    localStorage.setItem("theme", "light");
    new Function(THEME_SCRIPT)();
    expect(root.classList.contains("dark")).toBe(false);
  });

  it("defaults to dark when nothing is stored", () => {
    new Function(THEME_SCRIPT)();
    expect(root.classList.contains("dark")).toBe(true);
  });

  it("stores a choice, applies it, and tells subscribers", () => {
    root.classList.add("dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
    act(() => setTheme("light"));
    expect(localStorage.getItem("theme")).toBe("light");
    expect(root.classList.contains("dark")).toBe(false);
    expect(result.current).toMatchObject({ theme: "light", resolvedTheme: "light" });
  });

  it("follows the system preference for the system choice", () => {
    const { result } = renderHook(() => useTheme());
    act(() => setTheme("system"));
    const light = window.matchMedia("(prefers-color-scheme: light)").matches;
    expect(result.current.theme).toBe("system");
    expect(result.current.resolvedTheme).toBe(light ? "light" : "dark");
    expect(root.classList.contains("dark")).toBe(!light);
  });
});
