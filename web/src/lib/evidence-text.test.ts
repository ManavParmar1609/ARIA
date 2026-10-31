import { describe, expect, it } from "vitest";

import { evidenceDetail, evidenceTitle, featureName } from "./evidence-text";

describe("an evidence title", () => {
  it("reads a pattern as lines like it, with its changing parts as ellipses", () => {
    expect(evidenceTitle({ kind: "template", title: "16x Failed password for <*> port <*>" })).toBe(
      "16 lines like “Failed password for … port …”",
    );
    expect(evidenceTitle({ kind: "template", title: "1x POSSIBLE BREAK-IN ATTEMPT <*>" })).toBe(
      "1 line: “POSSIBLE BREAK-IN ATTEMPT …”",
    );
  });

  it("names a past incident without its record id", () => {
    expect(
      evidenceTitle({
        kind: "incident",
        title:
          "Similar incident syn-hdfs-block_serve_exceptions-51000: DataNodes failing to serve blocks (5 nodes) (SEV3; 6x on hdfs)",
      }),
    ).toBe("DataNodes failing to serve blocks (5 nodes): SEV3, seen 6 times on HDFS");
  });

  it("reads a past incident's runbook as its steps, and zero errors as none", () => {
    const detail = evidenceDetail({
      kind: "incident",
      detail:
        "Resolution: Followed runbook hdfs-block-serve: Restart the DataNode; Re-replicate the blocks.\nSummary: 0 error events on 0 of 30 nodes over 30 min (peak 0/min).",
    });
    expect(detail).toBe(
      "Resolution: Restart the DataNode; Re-replicate the blocks.\nSummary: no error lines over 30 minutes.",
    );
    expect(
      evidenceDetail({
        kind: "incident",
        detail: "Summary: 46 error events on 5 of 30 nodes over 12 min (peak 9/min).",
      }),
    ).toBe("Summary: 46 error events on 5 of 30 servers over 12 minutes (at most 9 a minute).");
  });

  it("names a rule by what it found and what it does, without its id", () => {
    expect(
      evidenceTitle({
        kind: "rule",
        title: "Rule error_storm (score SEV2): Errors on most servers",
      }),
    ).toBe("Errors on most servers (counts toward SEV2)");
    expect(evidenceTitle({ kind: "rule", title: "Rule data_loss (floor SEV2): Blocks lost" })).toBe(
      "Blocks lost (safety floor: SEV2)",
    );
  });

  it("reads the severity model's chances as percentages, and tiny ones as under 1%", () => {
    expect(
      evidenceTitle({
        kind: "model",
        title: "Severity probabilities: SEV1 0.03, SEV2 0.11, SEV3 0.5449, SEV4 0.001",
      }),
    ).toBe("How likely each level is: SEV1 3%, SEV2 11%, SEV3 54%, SEV4 under 1%");
    expect(
      evidenceTitle({ kind: "model", title: "Rule-score probabilities: SEV1 0.00, SEV2 1.00" }),
    ).toBe("Each level's share of the rule scores: SEV1 0%, SEV2 100%");
  });

  it("names the severity model's measurements in words", () => {
    expect(featureName("log1p.keyword_hits.crash")).toBe("words about crashes");
    expect(featureName("log1p.peak_errors_per_min")).toBe("errors a minute at the peak");
    expect(featureName("frac.WARN")).toBe("share of WARN lines");
    expect(featureName("rule_p.SEV2")).toBe("rules' score for SEV2");
  });

  it("reads a window's size as lines and errors", () => {
    expect(
      evidenceTitle({ kind: "feature", title: "158 events, 0 errors (0.0%) over 9.7 min" }),
    ).toBe("158 lines, no errors, over 9.7 minutes");
    expect(
      evidenceTitle({ kind: "feature", title: "2000 events, 1 errors (0.1%) over 12.0 min" }),
    ).toBe("2,000 lines, 1 error (0.1%), over 12.0 minutes");
  });

  it("leaves every other kind as recorded", () => {
    expect(evidenceTitle({ kind: "alert", title: "DiskFull firing on db-01" })).toBe(
      "DiskFull firing on db-01",
    );
  });
});
