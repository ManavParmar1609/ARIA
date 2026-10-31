import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Tabs, TabsList, TabsTrigger } from "./tabs";

function Two({ onPointerDown }: { onPointerDown?: () => void }) {
  return (
    <Tabs defaultValue="samples">
      <TabsList aria-label="What to triage">
        <TabsTrigger value="samples">Samples</TabsTrigger>
        <TabsTrigger value="own" onPointerDown={onPointerDown}>
          Your own logs
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

describe("tabs", () => {
  it("keep the focus ring for the keyboard: a press marks the tab until a key or a blur", () => {
    const pressed = vi.fn();
    render(<Two onPointerDown={pressed} />);
    const own = screen.getByRole("tab", { name: "Your own logs" });
    expect(own.className).toContain("data-pointer:focus-visible:outline-none");

    fireEvent.pointerDown(own);
    expect(own.dataset.pointer).toBe("");
    // The caller's own handler still runs.
    expect(pressed).toHaveBeenCalledTimes(1);
    // A modifier on its own is not keyboard use yet; any other key is.
    fireEvent.keyDown(own, { key: "Shift" });
    expect(own.dataset.pointer).toBe("");
    fireEvent.keyDown(own, { key: "ArrowLeft" });
    expect(own.dataset.pointer).toBeUndefined();

    fireEvent.pointerDown(own);
    fireEvent.blur(own);
    expect(own.dataset.pointer).toBeUndefined();
  });
});
