import { describe, expect, it } from "vitest";

import type { Evidence } from "@/lib/api/types";

import { answerNews, loadTurns, sourceName, sourceNames, sourceNumbers, type Turn } from "./ask";

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

  it("says ARIA is searching, then how much it found", () => {
    expect(answerNews(turn())).toBe("Searching ARIA's records");
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

  it("leaves an error to its own alert", () => {
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
