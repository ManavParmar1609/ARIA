import { describe, expect, it } from "vitest";

import { definitionFor } from "@/lib/definitions";

describe("definitionFor", () => {
  it("answers what a severity level means", () => {
    const sev1 = definitionFor("What does SEV1 mean?");
    expect(sev1?.term).toBe("SEV1");
    expect(sev1?.text).toMatch(/^SEV1 means critical\. Widespread outage/);
    expect(definitionFor("what is sev 3")?.term).toBe("SEV3");
    expect(definitionFor("What do the severity levels mean?")?.text).toContain("SEV4 means low");
  });

  it("answers words from ARIA's word list, by either of their names", () => {
    expect(definitionFor("What is a runbook?")?.term).toBe("Runbook");
    expect(definitionFor("What are runbooks?")?.term).toBe("Runbook");
    expect(definitionFor("What's a prediction set?")?.term).toBe("Short list (prediction set)");
    expect(definitionFor("Define safety floor")?.term).toBe("Safety floor");
  });

  it("leaves questions about incidents to the search", () => {
    expect(definitionFor("What does the runbook say to do first when DataNodes fail?")).toBeNull();
    expect(definitionFor("Have we seen ZooKeeper lose quorum before?")).toBeNull();
    expect(definitionFor("What did the investigation find?")).toBeNull();
    expect(definitionFor("What is SEV1 vs SEV2?")).toBeNull();
  });
});
