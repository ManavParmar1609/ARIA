import { render, screen, within } from "@testing-library/react";
import { type ComponentProps, createElement } from "react";
import { describe, expect, it } from "vitest";

import type { Evidence, LogEvent, SimilarIncident } from "@/lib/api/types";

import { EvidenceProvider } from "./evidence";
import { matchCaveat, pastKinds, SeenBefore } from "./seen-before";

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

  it("cite their sightings as sightings, not as the title's source", () => {
    const sightings = [incident("1 node"), incident("5 nodes")];
    const evidence = sightings.map(
      (each) =>
        ({
          id: each.evidence_id,
          kind: "incident",
          title: each.title,
          source: "memory.search",
        }) as Evidence,
    );
    const rows = createElement(SeenBefore, {
      incidents: sightings,
      retrieval: undefined,
      system: "hdfs",
    });
    // The rows go in as children, as JSX would pass them.
    const provider = { evidence, events: [] as LogEvent[] } as ComponentProps<
      typeof EvidenceProvider
    >;
    render(createElement(EvidenceProvider, provider, rows));
    // One row for the kind, titled by the closest sighting, with no citation beside the title.
    const title = screen.getByText("DataNodes failing to serve blocks (1 node)");
    expect(within(title.parentElement as HTMLElement).queryAllByRole("button")).toHaveLength(0);
    // Both sightings are cited together, under a name that says what they are.
    const cited = screen.getByText(/^The closest sightings:/);
    expect(
      within(cited)
        .getAllByRole("button")
        .map((chip) => chip.textContent),
    ).toEqual(["E-1 node", "E-5 nodes"]);
  });
});

describe("the caveat before past incidents", () => {
  it("says when every match comes from another system", () => {
    expect(matchCaveat([{ system: "bgl" }, { system: "hpc" }], "generic", 0.9)).toMatch(
      /^Nothing like this has been seen on this system\./,
    );
  });

  it("says when the matches are not close", () => {
    expect(matchCaveat([{ system: "hdfs" }], "hdfs", 0.1)).toMatch(/not a close match|None of/);
  });

  it("says nothing over close matches on the same system", () => {
    expect(matchCaveat([{ system: "hdfs" }], "hdfs", 0.8)).toBeNull();
    expect(matchCaveat([], "hdfs", 0)).toBeNull();
  });
});
