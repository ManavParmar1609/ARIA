import { act, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { loadDraft, logsHint, modelHint, megabytes, NewRun } from "./new-run";

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/runs/new",
  useSearchParams: () => new URLSearchParams("tab=own"),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/hooks", () => ({
  useCreateRun: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useModelKey: () => ({ data: undefined }),
  useSettingsView: () => ({ data: undefined }),
  // The Samples tab's, which stays closed here.
  useScenarios: () => ({ isPending: true }),
  useRealIncidents: () => ({ isPending: true }),
  useStartSample: () => ({}),
  useReplay: () => ({}),
}));

describe("logsHint", () => {
  it("says how pasted lines are protected", () => {
    expect(logsHint(null, false)).toContain("secrets redacted");
  });

  it("says on a public demo that only the visitor sees the incident, on a shared server", () => {
    const hint = logsHint(null, true);
    expect(hint).toContain("only you see it");
    expect(hint).toContain("shared server");
  });

  it("mentions a model key only where the server accepts one", () => {
    expect(logsHint(null, true)).not.toContain("model key");
    expect(logsHint(null, true, true)).toContain("If you add a model key");
  });

  it("says which model the lines go to while the model switch is on", () => {
    expect(logsHint(null, true, true, "own")).toContain("your own key's model");
    expect(logsHint(null, true, false, "shared")).toContain("the site's model.");
    expect(logsHint(null, true, true, "shared")).toContain("or to your own key's once you add one");
  });

  it("names no model while the model switch is off", () => {
    expect(logsHint(null, true, true, "off")).not.toMatch(/model/);
  });

  it("names what is wrong with the lines first", () => {
    const problem = "Paste at least one log line, or try a familiar log above.";
    expect(logsHint(problem, true)).toBe(problem);
  });
});

describe("modelHint", () => {
  it("says the visitor's own key answers first once one is saved", () => {
    expect(modelHint(["claude", "gemini"], "claude")).toContain(
      "your own Claude key answers first",
    );
  });

  it("points to Settings where visitors may bring a key", () => {
    expect(modelHint(["gemini"], null)).toContain("add your own key in Settings");
    expect(modelHint(["gemini"], "openai")).toContain("add your own key in Settings");
  });

  it("says when the site's key answers, and how many runs are left today", () => {
    expect(modelHint(["gemini"], null, { left: 2, per_visitor: 5 })).toContain(
      "On: the site's key answers (shared, limited: 2 left today).",
    );
    expect(modelHint(["gemini"], null, { left: 0, per_visitor: 5 })).toMatch(
      /^Offline for today: your share of the site's key is used/,
    );
  });

  it("keeps the offline promise where no keys are taken", () => {
    expect(modelHint([], null)).toContain("nothing leaves the server");
  });

  it("describes the switch as it is set", () => {
    const off = modelHint(["claude"], "claude", null, false);
    expect(off).toMatch(/^Off: /);
    expect(off).not.toContain("your own Claude key");
    expect(modelHint(["claude"], "claude", null, true)).not.toContain("Off:");
  });
});

describe("paste sizes", () => {
  it("round a paste up and a limit to the nearest tenth, in megabytes", () => {
    expect(megabytes(4 * 1024 * 1024)).toBe("4 MB");
    expect(megabytes(4.04 * 1024 * 1024, Math.ceil)).toBe("4.1 MB");
  });
});

describe("the pasted draft", () => {
  const storage = (value: string | null) => ({ getItem: () => value });

  it("comes back as it was left", () => {
    const draft = {
      title: "Checkout down",
      system: "linux",
      text: "ERROR one\nERROR two",
      useLlm: false,
      investigate: true,
      approval: false,
    };
    expect(loadDraft(storage(JSON.stringify(draft)))).toEqual(draft);
  });

  it("starts blank when nothing, or something unreadable, was kept", () => {
    const blank = loadDraft(undefined);
    expect(blank.text).toBe("");
    expect(blank.system).toBe("generic");
    expect(loadDraft(storage("not json"))).toEqual(blank);
    expect(loadDraft(storage(JSON.stringify({ text: 42, useLlm: "no" })))).toEqual(blank);
  });
});

describe("Your own logs", () => {
  const familiar = () => screen.getByRole("button", { name: /^Linux server/ });
  const box = () => screen.getByLabelText("Log lines");

  it("fills the box from a familiar log and, from the keyboard, takes focus there", () => {
    render(createElement(NewRun));
    // A key's click: no pointer pressed first.
    fireEvent.click(familiar());
    expect((box() as HTMLTextAreaElement).value).not.toBe("");
    expect(document.activeElement).toBe(box());
    // The count beside the box says how many lines came in.
    expect(screen.getByText(/^[\d,]+ lines$/).getAttribute("aria-live")).toBe("polite");
  });

  it("keeps focus on a tapped log, so no on-screen keyboard covers Start a triage", () => {
    render(createElement(NewRun));
    act(() => familiar().focus());
    fireEvent.pointerDown(familiar(), { pointerType: "touch" });
    fireEvent.click(familiar());
    expect((box() as HTMLTextAreaElement).value).not.toBe("");
    expect(document.activeElement).toBe(familiar());
  });

  it("keeps focus where it is on a screen that can't hover, such as a phone's", () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) => ({ matches: query === "(hover: none)", media: query }) as MediaQueryList,
    );
    render(createElement(NewRun));
    act(() => familiar().focus());
    fireEvent.click(familiar());
    expect(document.activeElement).toBe(familiar());
  });

  it("asks for lines with a placeholder that can't pass for a log", () => {
    render(createElement(NewRun));
    expect(box().getAttribute("placeholder")).toBe("Paste log lines here, one per line.");
    expect(box().className).toContain("placeholder:font-sans");
  });

  it("points a newcomer to the guide", () => {
    render(createElement(NewRun));
    expect(screen.getByRole("link", { name: "Start with the guide" }).getAttribute("href")).toBe(
      "/console/guide",
    );
  });
});
