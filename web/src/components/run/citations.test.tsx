import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Evidence } from "@/lib/api/types";

import { Citations, EvidenceProvider } from "./evidence";

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
