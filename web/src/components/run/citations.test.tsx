import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Evidence } from "@/lib/api/types";

import { Citations, EvidencePanel, EvidenceProvider, patternEvidence } from "./evidence";

const evidence = (id: string): Evidence =>
  ({ id, kind: "template", title: `Template ${id}`, source: "parser" }) as Evidence;

describe("Citations", () => {
  it("shows two sources, and the rest on request", () => {
    const ids = ["E1", "E2", "E3", "E4", "E5"];
    render(
      <EvidenceProvider evidence={ids.map(evidence)} events={[]}>
        <Citations ids={ids} />
      </EvidenceProvider>,
    );
    expect(screen.getAllByRole("button", { name: /^Evidence E\d/ })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Show 3 more sources" }));
    expect(screen.getAllByRole("button", { name: /^Evidence E\d/ })).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /more sources?$/ })).toBeNull();
  });
});

describe("a log pattern's citation", () => {
  const byId = new Map<string, Evidence>([
    ["E1", { id: "E1", kind: "feature", title: "125 events", source: "parser" } as Evidence],
    [
      "E4",
      {
        id: "E4",
        kind: "template",
        title: "12x lost the connection",
        source: "parser",
        data: { template_id: "t-lost" },
      } as Evidence,
    ],
  ]);

  it("is the pattern's own evidence", () => {
    expect(patternEvidence({ template_id: "t-lost", evidence_id: "E4" }, byId)).toEqual(["E4"]);
  });

  it("is nothing for a pattern that points at the whole window's counts", () => {
    expect(patternEvidence({ template_id: "t-quiet", evidence_id: "E1" }, byId)).toEqual([]);
    // Another pattern's evidence is not this one's either.
    expect(patternEvidence({ template_id: "t-quiet", evidence_id: "E4" }, byId)).toEqual([]);
  });

  it("stays when its evidence is missing, so the citation shows as missing", () => {
    expect(patternEvidence({ template_id: "t-gone", evidence_id: "E9" }, byId)).toEqual(["E9"]);
  });
});

describe("Back to the claim", () => {
  const arrow = () =>
    screen.getByRole("button", { name: "Back to the claim" }).querySelector("svg")?.classList;

  it("points down to a claim below the evidence panel", () => {
    render(
      <EvidenceProvider evidence={[evidence("E1")]} events={[]}>
        <EvidencePanel />
        <Citations ids={["E1"]} />
      </EvidenceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Evidence E1/ }));
    expect(arrow()?.contains("lucide-arrow-down")).toBe(true);
  });

  it("points up to a claim above it", () => {
    render(
      <EvidenceProvider evidence={[evidence("E1")]} events={[]}>
        <Citations ids={["E1"]} />
        <EvidencePanel />
      </EvidenceProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Evidence E1/ }));
    expect(arrow()?.contains("lucide-arrow-up")).toBe(true);
  });
});
