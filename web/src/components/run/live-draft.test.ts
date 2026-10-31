import { describe, expect, it } from "vitest";

import { draftSentences } from "./report-view";

describe("the report as it is written", () => {
  it("reads the sentences out of the writer's JSON, the last one unfinished", () => {
    const streamed =
      '{"summary": [{"text": "SEV3: a contained problem.", "evidence_ids": ["E9"]}, ' +
      '{"text": "Errors on 2 of 30 \\"data\\" servers", "evidence_ids": []}], ' +
      '"actions": [{"risk": "low", "text": "Confirm the sev';
    expect(draftSentences(streamed)).toEqual([
      "SEV3: a contained problem.",
      'Errors on 2 of 30 "data" servers',
      "Confirm the sev",
    ]);
  });

  it("shows nothing for JSON with no sentence yet, and plain text as it is", () => {
    expect(draftSentences('{"summary": [{"evidence_ids": ["E1"], ')).toEqual([]);
    expect(draftSentences("The disk filled up.")).toEqual(["The disk filled up."]);
  });
});
