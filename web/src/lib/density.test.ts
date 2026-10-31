import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { setDensity, useDensity } from "@/lib/density";

describe("row density", () => {
  it("starts comfortable, and remembers compact for the next visit", () => {
    localStorage.clear();
    const { result } = renderHook(() => useDensity());
    expect(result.current).toBe("comfortable");
    act(() => setDensity("compact"));
    expect(result.current).toBe("compact");
    expect(localStorage.getItem("aria.density")).toBe("compact");
    act(() => setDensity("comfortable"));
    expect(result.current).toBe("comfortable");
  });
});
