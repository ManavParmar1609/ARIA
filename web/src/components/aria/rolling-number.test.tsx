import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RollingNumber } from "./rolling-number";

describe("RollingNumber", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("keeps the real value as text and draws each digit as a strip resting on it", () => {
    const { container } = render(<RollingNumber value="98.0%" />);
    expect(screen.getByText("98.0%").className).toContain("sr-only");
    const face = container.querySelector(".roll-face");
    expect(face?.getAttribute("aria-hidden")).toBe("true");
    const strips = [...container.querySelectorAll<HTMLElement>(".roll-strip")];
    expect(strips.map((s) => s.style.getPropertyValue("--roll-to"))).toEqual(["9", "8", "0"]);
    expect(strips.map((s) => s.style.getPropertyValue("--roll-i"))).toEqual(["0", "1", "2"]);
    expect(strips[0]?.children).toHaveLength(10);
    const chars = [...container.querySelectorAll(".roll-char")].map((c) => c.textContent);
    expect(chars).toEqual([".", "%"]);
  });

  it("keeps real spaces between words, so a long value wraps like plain text", () => {
    const { container } = render(<RollingNumber value="87.3% to 93.3%" />);
    const face = container.querySelector(".roll-face");
    // 87.3%: a strip of 0-9 for each digit, with the dot and the percent sign between them
    const strip = "0123456789";
    const percent = `${strip}${strip}.${strip}%`;
    const words = [...(face?.querySelectorAll(".roll-word") ?? [])].map((w) => w.textContent);
    expect(words).toEqual([percent, "to", percent]);
    expect(face?.textContent?.split(" ")).toHaveLength(3);
    const order = [...container.querySelectorAll<HTMLElement>(".roll-strip")].map((s) =>
      s.style.getPropertyValue("--roll-i"),
    );
    expect(order).toEqual(["0", "1", "2", "3", "4", "5"]);
  });

  it("leaves a number that is already on screen at its value", () => {
    const { container } = render(<RollingNumber value="0.66 s" />);
    expect(container.querySelector<HTMLElement>(".roll")?.dataset.roll).toBeUndefined();
  });

  it("rolls a number up when it scrolls into view, then rests with crisp edges", () => {
    vi.useFakeTimers();
    let report: IntersectionObserverCallback = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: IntersectionObserverCallback) {
          report = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    const { container } = render(<RollingNumber value="42%" />);
    const root = container.querySelector<HTMLElement>(".roll");
    const seen = (top: number, isIntersecting: boolean) => {
      const entry = { boundingClientRect: { top }, rootBounds: { height: 800 }, isIntersecting };
      act(() =>
        report([entry as unknown as IntersectionObserverEntry], {} as IntersectionObserver),
      );
    };
    seen(1600, false);
    expect(root?.dataset.roll).toBe("ready");
    seen(500, true);
    expect(root?.dataset.roll).toBe("go");
    act(() => {
      vi.advanceTimersByTime(1200 + 70 * 2);
    });
    expect(root?.dataset.roll).toBe("done");
  });
});
