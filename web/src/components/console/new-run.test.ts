import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SAMPLE_LOGS } from "@/lib/samples";
import type * as Samples from "@/lib/samples";

import { familiarGroups } from "./familiar-logs";
import { loadDraft, logsHint, modelHint, megabytes, NewRun } from "./new-run";

const created = vi.hoisted(() => ({ mutate: vi.fn() }));
// How a familiar log's lines arrive: from the bundled files unless a test says otherwise.
const lines = vi.hoisted(() => ({ load: null as null | ((id: string) => Promise<string[]>) }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/runs/new",
  useSearchParams: () => new URLSearchParams("tab=own"),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/hooks", () => ({
  useCreateRun: () => ({ mutate: created.mutate, isPending: false, error: null }),
  useModelKey: () => ({ data: undefined }),
  useSettingsView: () => ({ data: undefined }),
  // The Samples tab's, which stays closed here.
  useScenarios: () => ({ isPending: true }),
  useRealIncidents: () => ({ isPending: true }),
  useStartSample: () => ({}),
  useReplay: () => ({}),
}));
vi.mock("@/lib/samples", async (importOriginal) => {
  const actual = await importOriginal<typeof Samples>();
  return { ...actual, sampleLines: (id: string) => (lines.load ?? actual.sampleLines)(id) };
});

/** A load that waits until the test lets it finish. */
function held(result: string[]) {
  let finish = () => {};
  const promise = new Promise<string[]>((resolve) => {
    finish = () => resolve(result);
  });
  return { promise, finish: () => act(async () => finish()) };
}

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
      sample: "linux.auth_failures",
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
    expect(blank.sample).toBeNull();
    expect(loadDraft(storage("not json"))).toEqual(blank);
    expect(loadDraft(storage(JSON.stringify({ text: 42, useLlm: "no", sample: 7 })))).toEqual(
      blank,
    );
  });
});

describe("familiar groups", () => {
  it("offer every sample once, the everyday groups first", () => {
    const groups = familiarGroups();
    const ids = groups.flatMap((group) => group.logs.map((log) => log.id));
    expect(ids.toSorted()).toEqual(SAMPLE_LOGS.map((log) => log.id).toSorted());
    const firstLater = groups.findIndex((group) => !group.everyday);
    expect(groups.slice(firstLater).every((group) => !group.everyday)).toBe(true);
    expect(groups.find((group) => group.everyday)?.logs[0]?.name).toBe("Linux server");
  });

  it("list a log from a system no group names under Other logs", () => {
    const groups = familiarGroups([
      {
        id: "spark.lost_executors",
        label: "Executors drop out",
        system: "spark",
        kind: "incident",
      },
    ]);
    expect(groups.map((group) => group.name)).toEqual(["Other logs"]);
    expect(groups[0]?.logs[0]?.name).toBe("Spark");
  });
});

describe("Your own logs", () => {
  const familiar = (name = /^Linux server/) => screen.getByRole("button", { name });
  const box = () => screen.getByLabelText("Log lines") as HTMLTextAreaElement;
  const filled = () => waitFor(() => expect(box().value).not.toBe(""));
  const everyday = familiarGroups()
    .filter((group) => group.everyday)
    .flatMap((group) => group.logs);

  // A test's page keeps its draft as it closes, so each test starts from a clean tab.
  beforeEach(() => {
    lines.load = null;
    created.mutate.mockClear();
    window.sessionStorage.clear();
  });

  it("fills the box from a familiar log and, from the keyboard, takes focus there", async () => {
    render(createElement(NewRun));
    // A key's click: no pointer pressed first.
    fireEvent.click(familiar());
    await filled();
    expect(document.activeElement).toBe(box());
    // The count beside the box says how many lines came in.
    expect(screen.getByText(/^[\d,]+ lines$/).getAttribute("aria-live")).toBe("polite");
  });

  it("keeps focus on a tapped log, so no on-screen keyboard covers Start a triage", async () => {
    render(createElement(NewRun));
    act(() => familiar().focus());
    fireEvent.pointerDown(familiar(), { pointerType: "touch" });
    fireEvent.click(familiar());
    await filled();
    expect(document.activeElement).toBe(familiar());
  });

  it("keeps focus where it is on a screen that can't hover, such as a phone's", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) => ({ matches: query === "(hover: none)", media: query }) as MediaQueryList,
    );
    render(createElement(NewRun));
    act(() => familiar().focus());
    fireEvent.click(familiar());
    await filled();
    expect(document.activeElement).toBe(familiar());
  });

  it("leaves focus where it went while the lines were loading", async () => {
    const load = held(["Dec 10 06:55:46 LabSZ sshd[24200]: Failed password for root"]);
    lines.load = () => load.promise;
    render(createElement(NewRun));
    act(() => familiar().focus());
    fireEvent.click(familiar());
    const guide = screen.getByRole("link", { name: "Start with the guide" });
    act(() => guide.focus());
    await load.finish();
    expect(box().value).toContain("Failed password");
    expect(document.activeElement).toBe(guide);
  });

  it("shows a handful of logs in groups, and every log on request", () => {
    render(createElement(NewRun));
    const picker = screen.getByRole("region", { name: "No logs at hand? Try a familiar one" });
    const logs = () => within(picker).getAllByRole("button", { pressed: false });
    expect(logs()).toHaveLength(everyday.length);
    expect(everyday.length).toBeLessThan(SAMPLE_LOGS.length);
    expect(within(picker).getByRole("heading", { name: "Security and sign-ins" })).toBeTruthy();
    const toggle = within(picker).getByRole("button", {
      name: `Show all ${SAMPLE_LOGS.length} logs`,
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.textContent).toBe("Show fewer logs");
    expect(logs()).toHaveLength(SAMPLE_LOGS.length);
    expect(within(picker).getByRole("heading", { name: "Supercomputers" })).toBeTruthy();
    // What it adds comes straight after it, so Tab goes there next.
    const added = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(added?.compareDocumentPosition(toggle)).toBe(Node.DOCUMENT_POSITION_PRECEDING);
  });

  it("says whether each log holds an incident or routine noise", () => {
    render(createElement(NewRun));
    expect(familiar().getAttribute("aria-label")).toBe(
      "Linux server: Sign-ins keep failing, incident",
    );
    expect(familiar(/^Mac:/).getAttribute("aria-label")).toBe("Mac: Harmless app errors, routine");
    expect(familiar(/^Mac:/).textContent).toContain("Routine");
  });

  it("marks a run from a familiar log as built from a sample, until its lines are edited", async () => {
    render(createElement(NewRun));
    fireEvent.click(familiar());
    await filled();
    expect(familiar().getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Start a triage" }));
    expect(created.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        title: "Linux server: Sign-ins keep failing",
        system: "linux",
        synthetic: true,
      }),
      expect.anything(),
    );
    // Edited, the lines are the visitor's own, and the log's title goes with it.
    fireEvent.change(box(), { target: { value: "ERROR checkout timed out" } });
    expect(familiar().getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Start a triage" }));
    expect(created.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        title: undefined,
        logs: ["ERROR checkout timed out"],
        synthetic: false,
      }),
      expect.anything(),
    );
  });

  it("keeps a title the visitor typed when they edit a familiar log's lines", async () => {
    render(createElement(NewRun));
    fireEvent.click(familiar());
    await filled();
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Checkout down" } });
    fireEvent.change(box(), { target: { value: "ERROR checkout timed out" } });
    fireEvent.click(screen.getByRole("button", { name: "Start a triage" }));
    expect(created.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({ title: "Checkout down", synthetic: false }),
      expect.anything(),
    );
  });

  it("says when a log's lines can't load, and loads them when it is chosen again", async () => {
    lines.load = () => Promise.reject(new Error("The chunk failed to load"));
    render(createElement(NewRun));
    fireEvent.click(familiar(/^Mac:/));
    await screen.findByText("Couldn’t load it. Choose it to try again.");
    expect(screen.getByRole("status").textContent).toBe(
      "The Mac log couldn’t load. Choose it to try again.",
    );
    // The log says so itself, in what a screen reader reads out for it too.
    expect(familiar(/^Mac:/).getAttribute("aria-label")).toBe(
      "Mac: Harmless app errors, routine. Couldn’t load it. Choose it to try again.",
    );
    expect(box().value).toBe("");
    lines.load = null;
    fireEvent.click(familiar(/^Mac:/));
    await filled();
    expect(screen.queryByText("Couldn’t load it. Choose it to try again.")).toBeNull();
    expect(familiar(/^Mac:/).getAttribute("aria-pressed")).toBe("true");
  });

  it("says a log is loading, and fills the box with the latest pick only", async () => {
    const slow = held(["a line from the Mac"]);
    lines.load = (id) =>
      id === "mac.cocoa_scripting_noise" ? slow.promise : Promise.resolve(["a line from Linux"]);
    render(createElement(NewRun));
    fireEvent.click(familiar(/^Mac:/));
    expect(screen.getByRole("status").textContent).toBe("Loading the Mac log.");
    fireEvent.click(familiar());
    await waitFor(() => expect(box().value).toBe("a line from Linux"));
    await slow.finish();
    expect(box().value).toBe("a line from Linux");
    expect(familiar().getAttribute("aria-pressed")).toBe("true");
    expect(familiar(/^Mac:/).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("comes back to a log from the longer list with the list open", () => {
    const draft = { text: "a line", sample: "bgl.kernel_panic", title: "BlueGene/L" };
    window.sessionStorage.setItem("aria:own-logs", JSON.stringify(draft));
    render(createElement(NewRun));
    expect(screen.getByRole("button", { name: "Show fewer logs" })).toBeTruthy();
    expect(familiar(/^BlueGene\/L: Compute nodes crash/).getAttribute("aria-pressed")).toBe("true");
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
