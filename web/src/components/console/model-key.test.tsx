import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelKeyPanel } from "./model-key";

const save = vi.hoisted(() => ({
  mutate: vi.fn(),
  reset: vi.fn(),
  isPending: false,
  data: undefined,
  error: null,
}));
vi.mock("@/lib/api/hooks", () => ({
  useModelKey: () => ({ isPending: false, isError: false, data: { provider: null, ending: null } }),
  useSaveModelKey: () => save,
  useForgetModelKey: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("saving a model key", () => {
  beforeEach(() => {
    save.isPending = false;
  });

  it("keeps Check and save key in the Tab order, and says what is missing when pressed empty", () => {
    render(<ModelKeyPanel kinds={["gemini"]} />);
    const button = screen.getByRole("button", { name: "Check and save key" });
    expect(button.hasAttribute("disabled")).toBe(false);
    fireEvent.click(button);
    expect(screen.getByRole("alert").textContent).toBe("Paste your API key first.");
    const field = screen.getByLabelText("API key");
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    expect(save.mutate).not.toHaveBeenCalled();

    // Typing clears the message; pressing again sends the key to be checked.
    fireEvent.change(field, { target: { value: "AIza-example-key-for-the-test-only" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(button);
    expect(save.mutate).toHaveBeenCalledWith(
      { provider: "gemini", key: "AIza-example-key-for-the-test-only" },
      expect.anything(),
    );
  });

  it("waits, still focusable, while a key is being checked", () => {
    save.isPending = true;
    render(<ModelKeyPanel kinds={["gemini"]} />);
    const button = screen.getByRole("button", { name: "Checking the key…" });
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(button);
    expect(save.mutate).not.toHaveBeenCalled();
  });
});
