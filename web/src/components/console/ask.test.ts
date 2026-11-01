import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { AskResponse, Evidence } from "@/lib/api/types";
import { UNREACHABLE } from "@/lib/unreachable";

import {
  Ask,
  answerNews,
  answerText,
  loadTurns,
  resetChat,
  sourceLink,
  sourceName,
  sourceNames,
  sourceNumbers,
  type Turn,
} from "./ask";

const route = vi.hoisted(() => ({ search: "" }));
const api = vi.hoisted(() => ({
  ask: { mutateAsync: vi.fn() },
  run: { data: undefined as { title: string } | undefined, isError: false, error: null },
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(route.search),
}));
vi.mock("@/lib/api/hooks", () => ({
  useAsk: () => api.ask,
  useRuns: () => ({ data: { runs: [] } }),
  useRun: () => ({ ...api.run, refetch: vi.fn() }),
}));

describe("Ask ARIA's sources", () => {
  it("numbers sources in the order the answer first cites them", () => {
    const numbers = sourceNumbers({
      answer: [
        { text: "a", evidence_ids: ["E7", "E2"] },
        { text: "b", evidence_ids: ["E2", "E9"] },
      ],
    });
    expect([...numbers]).toEqual([
      ["E7", "1"],
      ["E2", "2"],
      ["E9", "3"],
    ]);
  });

  it("names a past incident by its own title and says when it was built from a sample", () => {
    const incident = {
      id: "E1",
      kind: "incident",
      title: "Past incident syn-zk-1: ZooKeeper quorum loss (SEV2, zookeeper)",
      source: "memory.search",
      data: { title: "ZooKeeper quorum loss", synthetic: true },
    } as unknown as Evidence;
    expect(sourceName(incident)).toBe("ZooKeeper quorum loss (built from a sample)");
    // A source card says "built from a sample" beside the kind instead.
    expect(sourceName(incident, { sample: false })).toBe("ZooKeeper quorum loss");
    expect(sourceName({ ...incident, data: { title: "Disk full" } } as Evidence)).toBe("Disk full");
    const line = { ...incident, kind: "log", title: "line 4: oops", data: {} } as Evidence;
    expect(sourceName(line)).toBe("line 4: oops");
  });

  it("names rules and runbooks by what they are about, not by their IDs", () => {
    const rule = {
      id: "E2",
      kind: "rule",
      title: "Rule R12 (floor SEV2): Disk full on a data node",
      source: "severity.rules",
      data: {},
    } as unknown as Evidence;
    // The list puts each source's kind before its name, so the name does not repeat it.
    expect(sourceName(rule)).toBe("Disk full on a data node");
    const runbook = { ...rule, kind: "runbook", title: "Runbook hdfs-disk-full: HDFS disk full" };
    expect(sourceName(runbook as Evidence)).toBe("HDFS disk full");
    const similar = {
      ...rule,
      kind: "incident",
      title: "Similar incident syn-hdfs-1: DataNodes failing to serve blocks (SEV3; 4x on hdfs)",
      data: { synthetic: true },
    };
    expect(sourceName(similar as Evidence)).toBe(
      "DataNodes failing to serve blocks (built from a sample)",
    );
  });

  it("tells apart two past incidents with one title by the day each was last seen", () => {
    const twin = (id: string, ts: string) =>
      ({
        id,
        kind: "incident",
        title: `Past incident ${id}: Quorum loss`,
        source: "memory.search",
        data: { title: "Quorum loss" },
        ts,
      }) as unknown as Evidence;
    const other = { ...twin("E3", "2026-03-01T00:00:00Z"), data: { title: "Disk full" } };
    const names = sourceNames([
      twin("E1", "2026-03-02T10:00:00Z"),
      twin("E2", "2026-04-12T16:12:00Z"),
      other as Evidence,
    ]);
    expect(names.get("E1")).toBe("Quorum loss, last seen 2 Mar 2026");
    expect(names.get("E2")).toBe("Quorum loss, last seen 12 Apr 2026");
    expect(names.get("E3")).toBe("Disk full");
  });

  it("links each source to its record: a runbook, the library, or the incident it came from", () => {
    const base = { source: "memory.search", ts: null, detail: "" };
    const runbook = {
      ...base,
      id: "E5",
      kind: "runbook",
      title: "Runbook zookeeper-quorum-loss: ZooKeeper quorum loss",
      data: { slug: "zookeeper-quorum-loss" },
    } as unknown as Evidence;
    expect(sourceLink(runbook, null)).toEqual({
      href: "/console/runbooks/zookeeper-quorum-loss",
      label: "Open the runbook",
    });
    const curated = {
      ...base,
      id: "E1",
      kind: "incident",
      title: "Past incident syn-zk-1: ZooKeeper quorum loss (SEV2, zookeeper)",
      data: { incident_id: "syn-zk-1", title: "ZooKeeper quorum loss", synthetic: true },
    } as unknown as Evidence;
    expect(sourceLink(curated, null)).toEqual({
      href: "/console/memory?q=ZooKeeper%20quorum%20loss",
      label: "Find it in the incident library",
    });
    // An approved incident's entry is named after the run it came from.
    const learned = { ...curated, data: { incident_id: "inc-20261031-ab12" } } as Evidence;
    expect(sourceLink(learned, null)?.href).toBe("/console/runs/run-20261031-ab12");
    // What a triage recorded opens on that incident's page; without one there is nowhere to go.
    const cause = { ...base, id: "E9", kind: "hypothesis", title: "H1 supported: x", data: {} };
    expect(sourceLink(cause as Evidence, "run-7")?.href).toBe("/console/runs/run-7");
    expect(sourceLink(cause as Evidence, null)).toBeNull();
  });
});

const SOURCES = [
  {
    id: "E1",
    kind: "incident",
    title: "Past incident syn-zk-1: ZooKeeper quorum loss (SEV2, zookeeper)",
    source: "memory.search",
    detail: "Resolution: Restore connectivity between peers first.",
    data: { incident_id: "syn-zk-1", title: "ZooKeeper quorum loss", synthetic: true },
    ts: null,
  },
  {
    id: "E2",
    kind: "runbook",
    title: "Runbook zookeeper-quorum-loss: ZooKeeper quorum loss",
    source: "runbooks",
    detail: "1. Restore connectivity between peers first.",
    data: { slug: "zookeeper-quorum-loss" },
    ts: null,
  },
] as unknown as Evidence[];

const ANSWER = {
  answer: [
    { text: "A past incident was fixed by restoring connectivity.", evidence_ids: ["E1"] },
    { text: "The runbook starts the same way.", evidence_ids: ["E2", "E1"] },
  ],
  evidence: SOURCES,
  insufficient_evidence: false,
  answered_by: "retrieval",
  follow_ups: [],
  notes: [],
  model: null,
} as AskResponse;

describe("an answer as text to paste elsewhere", () => {
  it("keeps each point's source numbers and lists the sources after the points", () => {
    const turn: Turn = { id: "t1", question: "How was it fixed?", runId: null, answer: ANSWER };
    expect(answerText(turn)).toBe(
      [
        "A past incident was fixed by restoring connectivity. [1]",
        "The runbook starts the same way. [2][1]",
        "Sources:\n1. Past incident: ZooKeeper quorum loss (built from a sample)\n2. Runbook: ZooKeeper quorum loss",
      ].join("\n\n"),
    );
  });

  it("copies a word's meaning, and has nothing to copy when nothing answered", () => {
    const definition = { term: "SEV1", text: "SEV1 means critical." };
    expect(answerText({ id: "t2", question: "q", runId: null, definition })).toBe(
      "SEV1: SEV1 means critical.",
    );
    const empty = { ...ANSWER, answer: [] };
    expect(answerText({ id: "t3", question: "q", runId: null, answer: empty })).toBe("");
  });
});

describe("what a screen reader hears about an answer", () => {
  const turn = (changes: Partial<Turn> = {}): Turn => ({
    id: "q1",
    question: "How was the quorum loss fixed?",
    runId: null,
    ...changes,
  });
  const answer = (claims: string[][], partial = false) =>
    ({
      answer: claims.map((ids, i) => ({ text: `Point ${i}`, evidence_ids: ids })),
      evidence: [],
      insufficient_evidence: partial,
      answered_by: "retrieval",
      follow_ups: [],
    }) as unknown as Turn["answer"];

  it("says ARIA is thinking, then how much it found", () => {
    expect(answerNews(turn())).toBe("ARIA is thinking…");
    expect(answerNews(turn({ answer: answer([["E1"], ["E1", "E2"]]) }))).toBe(
      "ARIA answered: 2 points, from 2 sources.",
    );
    expect(answerNews(turn({ answer: answer([["E1"]], true) }))).toBe(
      "ARIA found part of an answer: 1 point, from 1 source.",
    );
    expect(answerNews(turn({ answer: answer([]) }))).toBe(
      "Nothing in ARIA's records answers this.",
    );
  });

  it("leaves an error to say itself", () => {
    expect(answerNews(turn({ error: "ARIA is busy" }))).toBe("");
    expect(answerNews(undefined)).toBe("");
  });
});

describe("loadTurns", () => {
  const store = (value: string | null) => ({ getItem: () => value });

  it("brings back answered questions and drops ones still waiting", () => {
    const kept = [
      { id: "a", question: "What failed first?", runId: null, error: "ARIA is busy." },
      { id: "b", question: "Still asking?", runId: null },
    ];
    expect(loadTurns(store(JSON.stringify(kept))).map((t) => t.id)).toEqual(["a"]);
  });

  it("starts empty when nothing is kept, or what is kept is not a conversation", () => {
    expect(loadTurns(undefined)).toEqual([]);
    expect(loadTurns(store(null))).toEqual([]);
    expect(loadTurns(store("{not json"))).toEqual([]);
    expect(loadTurns(store('{"id": "a"}'))).toEqual([]);
  });
});

describe("an Ask source's name", () => {
  const base = { id: "E7", source: "investigator", ts: null, detail: "", data: {} };

  it("reads a tested cause by what the evidence did to it", () => {
    const supported = { ...base, kind: "hypothesis", title: "H2 supported: disk <*> is full" };
    expect(sourceName(supported as unknown as Evidence)).toBe(
      "Backed by the evidence: disk … is full",
    );
    const refuted = { ...base, kind: "hypothesis", title: "H1 refuted: the network dropped" };
    expect(sourceName(refuted as unknown as Evidence)).toBe("Ruled out: the network dropped");
  });

  it("names an investigation check by what it looked at", () => {
    const tool = { ...base, kind: "tool", title: "component_timeline: 12 events over 3 minutes" };
    expect(sourceName(tool as unknown as Evidence)).toBe("Over time: 12 events over 3 minutes");
  });
});

describe("Ask ARIA's word answers", () => {
  it("keeps a word's meaning in the conversation and says where it came from", () => {
    const turn: Turn = {
      id: "t1",
      question: "What does SEV1 mean?",
      runId: null,
      definition: { term: "SEV1", text: "SEV1 means critical." },
    };
    const storage = { getItem: () => JSON.stringify([turn]) };
    expect(loadTurns(storage)).toEqual([turn]);
    expect(answerNews(turn)).toBe("ARIA answered from its word list: what SEV1 means.");
  });
});

describe("chatting with ARIA", () => {
  const ZOOKEEPER = "Have we seen ZooKeeper lose quorum before, and how was it fixed?";
  const box = () => screen.getByLabelText<HTMLTextAreaElement>("Your question");
  const log = () => screen.getByRole("log", { name: "Conversation" });
  const type = (text: string) => fireEvent.change(box(), { target: { value: text } });

  beforeEach(() => {
    route.search = "";
    api.run = { data: undefined, isError: false, error: null };
    api.ask.mutateAsync.mockReset();
    api.ask.mutateAsync.mockReturnValue(new Promise(() => {}));
    resetChat();
  });

  it("opens on a greeting that says what ARIA answers from, with questions to try", () => {
    render(createElement(Ask));
    expect(screen.getByText("What would you like to know?")).toBeTruthy();
    expect(screen.getByText(/answers from its incident library and runbooks/)).toBeTruthy();
    const tries = screen.getByRole("heading", { name: "Try one of these" }).nextElementSibling;
    expect(within(tries as HTMLElement).getAllByRole("button")).toHaveLength(4);
    // Nothing to send yet, and no conversation to clear.
    expect(screen.getByRole("button", { name: "Send question" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(screen.queryByRole("button", { name: "New chat" })).toBeNull();
  });

  it("sends with Enter, and keeps focus in the box for the next question", () => {
    render(createElement(Ask));
    act(() => box().focus());
    type("How was ZooKeeper quorum loss fixed before?");
    // Enter is taken for sending: no new line goes into the box.
    expect(fireEvent.keyDown(box(), { key: "Enter" })).toBe(false);
    expect(api.ask.mutateAsync).toHaveBeenCalledWith({
      question: "How was ZooKeeper quorum loss fixed before?",
      run_id: null,
    });
    expect(within(log()).getByRole("heading", { level: 2 }).textContent).toBe(
      "You asked: How was ZooKeeper quorum loss fixed before?",
    );
    expect(within(log()).getByText("About: all past incidents and runbooks")).toBeTruthy();
    expect(box().value).toBe("");
    expect(document.activeElement).toBe(box());
  });

  it("starts a new line with Shift+Enter instead of sending", () => {
    render(createElement(Ask));
    type("Which errors appeared");
    expect(fireEvent.keyDown(box(), { key: "Enter", shiftKey: true })).toBe(true);
    expect(api.ask.mutateAsync).not.toHaveBeenCalled();
    expect(box().value).toBe("Which errors appeared");
    expect(within(log()).queryAllByRole("article")).toHaveLength(0);
  });

  it("sends a suggested question when it is pressed, and hands focus to the box", () => {
    render(createElement(Ask));
    fireEvent.click(screen.getByRole("button", { name: ZOOKEEPER }));
    expect(api.ask.mutateAsync).toHaveBeenCalledWith({ question: ZOOKEEPER, run_id: null });
    expect(within(log()).getAllByRole("article")).toHaveLength(1);
    expect(document.activeElement).toBe(box());
  });

  it("shows ARIA thinking, then its answer with numbered sources that open their records", async () => {
    let answer: (value: AskResponse) => void = () => {};
    api.ask.mutateAsync.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    render(createElement(Ask));
    fireEvent.click(screen.getByRole("button", { name: ZOOKEEPER }));
    expect(await within(log()).findByText("ARIA is thinking…")).toBeTruthy();

    await act(async () => answer(ANSWER));
    const exchange = within(log()).getByRole("article");
    expect(within(exchange).getByText("ARIA answered: 2 points, from 2 sources.")).toBeTruthy();
    expect(within(exchange).queryByText("ARIA is thinking…")).toBeNull();
    expect(within(exchange).getByRole("heading", { name: "Sources" })).toBeTruthy();
    const runbook = within(exchange).getByRole("link", { name: /^2 Runbook ZooKeeper quorum/ });
    expect(runbook.getAttribute("href")).toBe("/console/runbooks/zookeeper-quorum-loss");
    expect(within(exchange).getByRole("button", { name: "Copy this answer" })).toBeTruthy();
    // Other good questions stay in view under the latest answer.
    const more = screen.getByRole("heading", { name: "You could also ask" }).nextElementSibling;
    expect(within(more as HTMLElement).getAllByRole("button")).toHaveLength(3);

    // A citation opens what its source says beneath the cards.
    fireEvent.click(within(exchange).getAllByRole("button", { name: /^Source 1:/ })[0]!);
    const detail = within(exchange).getByRole("region", { name: "Source 1" });
    expect(detail.textContent).toContain("Resolution: Restore connectivity between peers first.");
  });

  it("answers what a word means from the word list, without asking the server", () => {
    render(createElement(Ask));
    type("What does SEV1 mean?");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(api.ask.mutateAsync).not.toHaveBeenCalled();
    expect(within(log()).getByText("SEV1")).toBeTruthy();
    expect(within(log()).getByRole("link", { name: "Words used in ARIA" })).toBeTruthy();
  });

  it("says when the server did not answer, and tries again when asked", async () => {
    api.ask.mutateAsync.mockRejectedValueOnce(new ApiError(503, UNREACHABLE));
    render(createElement(Ask));
    type("Which past incidents involved SSH brute-force attempts?");
    await act(async () => {
      fireEvent.keyDown(box(), { key: "Enter" });
    });
    expect(within(log()).getByText(UNREACHABLE)).toBeTruthy();
    api.ask.mutateAsync.mockResolvedValueOnce(ANSWER);
    await act(async () => {
      fireEvent.click(within(log()).getByRole("button", { name: "Try again" }));
    });
    expect(api.ask.mutateAsync).toHaveBeenCalledTimes(2);
    expect(within(log()).queryByText(UNREACHABLE)).toBeNull();
    expect(within(log()).getByRole("heading", { name: "Sources" })).toBeTruthy();
  });

  it("clears the conversation with New chat, and can bring it back", async () => {
    api.ask.mutateAsync.mockResolvedValue(ANSWER);
    render(createElement(Ask));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: ZOOKEEPER }));
    });
    expect(window.sessionStorage.getItem("aria:ask-chat")).toContain(ZOOKEEPER);

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(within(log()).queryAllByRole("article")).toHaveLength(0);
    expect(screen.getByText("What would you like to know?")).toBeTruthy();
    expect(window.sessionStorage.getItem("aria:ask-chat")).toBeNull();
    expect(document.activeElement).toBe(box());

    fireEvent.click(screen.getByRole("button", { name: "Bring back the last one" }));
    expect(within(log()).getAllByRole("article")).toHaveLength(1);
  });

  it("keeps the conversation while the reader visits other pages, answers included", async () => {
    let answer: (value: AskResponse) => void = () => {};
    api.ask.mutateAsync.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const page = render(createElement(Ask));
    fireEvent.click(screen.getByRole("button", { name: ZOOKEEPER }));
    page.unmount();
    // The answer arrives while the reader is on another page.
    await act(async () => answer(ANSWER));

    render(createElement(Ask));
    const exchange = within(log()).getByRole("article");
    expect(within(exchange).getByRole("heading", { name: "Sources" })).toBeTruthy();
    expect(loadTurns(window.sessionStorage).map((t) => t.question)).toEqual([ZOOKEEPER]);
  });

  it("asks about the incident in the link, and says so under the question", () => {
    route.search = "run=run-7";
    api.run = { data: { title: "SEV2 · Quorum loss in ZooKeeper" }, isError: false, error: null };
    render(createElement(Ask));
    expect(screen.getByText(/answers from this incident's logs/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "What did the investigation find?" }));
    expect(api.ask.mutateAsync).toHaveBeenCalledWith({
      question: "What did the investigation find?",
      run_id: "run-7",
    });
    expect(within(log()).getByText("About: Quorum loss in ZooKeeper")).toBeTruthy();
  });
});
