import { describe, expect, it } from "vitest";

import { SAMPLE_LOGS, sampleLines } from "./samples";

describe("the sample logs", () => {
  it("each have lines to load, no more than the export keeps", async () => {
    expect(SAMPLE_LOGS.length).toBeGreaterThan(0);
    for (const sample of SAMPLE_LOGS) {
      const lines = await sampleLines(sample.id);
      expect(lines.length, sample.id).toBeGreaterThan(0);
      expect(lines.length, sample.id).toBeLessThanOrEqual(220);
    }
  });

  it("keep the ids the chat and earlier drafts name", () => {
    const ids = SAMPLE_LOGS.map((sample) => sample.id);
    for (const id of [
      "hdfs.block_serve_exceptions",
      "openssh.bruteforce",
      "zookeeper.quorum_connection_loss",
      "mac.cocoa_scripting_noise",
      "linux.auth_failures",
      "apache.mod_jk_worker_error",
      "android.permission_noise",
      "openstack.image_cache_missing",
    ]) {
      expect(ids).toContain(id);
    }
  });

  it("say whether each holds an incident or routine noise", () => {
    expect(new Set(SAMPLE_LOGS.map((sample) => sample.kind))).toEqual(
      new Set(["incident", "routine"]),
    );
  });

  it("refuse a sample that is not there", async () => {
    await expect(sampleLines("nothing.here")).rejects.toThrow("no sample called nothing.here");
  });
});
