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
  it("applies a stored dark theme before first paint", () => {
    localStorage.setItem("theme", "dark");
    new Function(THEME_SCRIPT)();
    expect(root.classList.contains("dark")).toBe(true);
  });

  it("defaults to light when nothing is stored", () => {
    root.classList.add("dark");
    new Function(THEME_SCRIPT)();
    expect(root.classList.contains("dark")).toBe(false);
  });

  it("stores a choice, applies it, and tells subscribers", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
    act(() => setTheme("dark"));
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(root.classList.contains("dark")).toBe(true);
    expect(result.current).toMatchObject({ theme: "dark", resolvedTheme: "dark" });
  });

  it("follows the system preference for the system choice", () => {
    const { result } = renderHook(() => useTheme());
    act(() => setTheme("system"));
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    expect(result.current.theme).toBe("system");
    expect(result.current.resolvedTheme).toBe(dark ? "dark" : "light");
    expect(root.classList.contains("dark")).toBe(dark);
  });
});
