import { describe, expect, it } from "vitest";

import evals from "@/data/eval-results.json";
import * as raw from "@/test/domains";

import {
  DOMAINS,
  readDomains,
  type FaultWindows,
  type IssuePriority,
  type SecurityAlerts,
} from "./domains";

const read = (domains: unknown = raw.domains()) => readDomains(domains);
const suite = <T>(key: string, domains?: unknown) =>
  read(domains)?.results.find((r) => r.key === key) as T | undefined;

describe("the new-domain results", () => {
  it("reads nothing when the results have no new domains yet", () => {
    expect(readDomains(undefined)).toBeNull();
    expect(readDomains({})).toBeNull();
    expect(readDomains([])).toBeNull();
  });

  it("reads every suite, in the order of the full write-up", () => {
    expect(read()?.results.map((r) => r.key)).toEqual([...DOMAINS]);
    expect(read()?.notRun).toEqual([]);
  });

  it("lists a suite whose data was not downloaded as not run yet", () => {
    const missing = { missing: "download it with: aria data download --source itbench-lite" };
    const partly = read({ ...raw.domains(), itbench: missing });
    expect(partly?.results.map((r) => r.key)).not.toContain("itbench");
    expect(partly?.notRun).toEqual(["itbench"]);
    expect(read({ jira: missing })).toEqual({ results: [], notRun: ["jira"] });
  });

  it("leaves out a suite that lacks a part the page needs, and reads the rest", () => {
    const broken = raw.faults();
    delete (broken.aria as Partial<typeof broken.aria>).ranking;
    const keys = read({ ...raw.domains(), rcaeval: broken })?.results.map((r) => r.key);
    expect(keys).toEqual(["ait-ads", "anomod", "itbench", "jira", "nezha"]);
  });

  it("keeps each share with its interval, and a miss rate with its bound", () => {
    const alerts = suite<SecurityAlerts>("ait-ads");
    expect(alerts?.harmfulMissed).toEqual({
      hits: 10,
      of: 16,
      share: 0.625,
      ci: [0.525, 0.725],
      upper: 0.745,
    });
    expect(alerts?.ranking.auroc).toBe(0.6);
    expect(alerts?.methods.map((m) => m.key)).toEqual([
      "aria",
      "rules_only",
      "model_only",
      "keyword",
      "ids_level",
    ]);
    expect(alerts?.detectorsMissed?.hits).toBe(16);
  });

  it("marks the attack steps that mean a break-in or harm", () => {
    const steps = suite<SecurityAlerts>("ait-ads")?.steps ?? [];
    expect(Object.fromEntries(steps.map((s) => [s.key, s.harmful]))).toEqual({
      network_scans: false,
      webshell: true,
      cracking: true,
      reverse_shell: true,
      privilege_escalation: true,
    });
  });

  it("reads the kinds of fault and the days where a suite has them", () => {
    const nezha = suite<FaultWindows>("nezha");
    expect(nezha?.faults.map((f) => f.key)).toEqual(["cpu_contention", "exception"]);
    expect(nezha?.days).toBe(2);
    expect(nezha?.windowMin).toBe(1);
    const rcaeval = suite<FaultWindows>("rcaeval");
    expect(rcaeval?.days).toBeNull();
    expect(rcaeval?.systems.map((s) => [s.key, s.cases, s.detail?.healthy.hits])).toEqual([
      ["OB", 20, 0],
      ["SS", 20, 16],
    ]);
  });

  it("reads each tracker's tickets and every tracker's together", () => {
    const jira = suite<IssuePriority>("jira");
    expect(jira?.trackers.map((t) => [t.key, t.tickets])).toEqual([
      ["Apache", 2000],
      ["Jira", 1000],
    ]);
    expect(jira?.pooled.methods.find((m) => m.key === "aria")?.predicted).toEqual({ "3": 3000 });
  });

  const published = (evals as unknown as Record<string, unknown>).domains as
    Record<string, unknown> | undefined;

  it.runIf(!published)("shows nothing new while the published results have none", () => {
    expect(readDomains(published)).toBeNull();
  });

  it.skipIf(!published)("reads every suite the published results ran", () => {
    const ran = DOMAINS.filter((key) => {
      const summary = published?.[key];
      return typeof summary === "object" && summary !== null && !("missing" in summary);
    });
    expect(readDomains(published)?.results.map((r) => r.key)).toEqual(ran);
  });
});
