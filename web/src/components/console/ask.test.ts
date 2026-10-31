import { describe, expect, it } from "vitest";

import type { Evidence } from "@/lib/api/types";

import { sourceName, sourceNumbers } from "./ask";

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
});
