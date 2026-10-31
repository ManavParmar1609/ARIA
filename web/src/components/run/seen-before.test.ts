import { describe, expect, it } from "vitest";

import type { SimilarIncident } from "@/lib/api/types";

import { pastKinds } from "./seen-before";

const incident = (id: string, changes: Partial<SimilarIncident> = {}): SimilarIncident => ({
  incident_id: id,
  title: `DataNodes failing to serve blocks (${id})`,
  system: "hdfs",
  failure_mode: "block_serve_exceptions",
  severity: "SEV2",
  score: 0.9,
  lexical_score: 0.5,
  dense_score: 0.5,
  occurrences: 6,
  resolution: "Restart the DataNode",
  source: "curated",
  evidence_id: `E-${id}`,
  ...changes,
});

describe("past incidents of one kind", () => {
  it("show once, closest first, and cite every sighting", () => {
    const kinds = pastKinds([
      incident("a"),
      incident("b", { system: "bgl", failure_mode: "kernel_panic", resolution: "Reboot" }),
      incident("c"),
    ]);
    expect(kinds.map((kind) => kind.lead.incident_id)).toEqual(["a", "b"]);
    expect(kinds[0]?.all.map((each) => each.evidence_id)).toEqual(["E-a", "E-c"]);
  });

  it("stay apart when they were fixed differently", () => {
    const kinds = pastKinds([incident("a"), incident("b", { resolution: "Replace the disk" })]);
    expect(kinds).toHaveLength(2);
  });
});
