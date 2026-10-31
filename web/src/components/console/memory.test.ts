import { describe, expect, it } from "vitest";

import type { IncidentOut } from "@/lib/api/types";

import { oneOfEach } from "./memory";

const entry = (id: string, changes: Partial<IncidentOut> = {}): IncidentOut =>
  ({
    incident_id: id,
    title: "SSH brute-force attempts against 3 hosts",
    system: "openssh",
    failure_mode: "bruteforce",
    severity: "SEV2",
    summary: "Repeated failed logins.",
    resolution: "Block the source addresses",
    occurrences: 1,
    last_seen: "2026-10-01T10:00:00Z",
    source: "curated",
    synthetic: true,
    ...changes,
  }) as IncidentOut;

describe("the incident library", () => {
  it("lists an incident it holds twice once, counting both sightings", () => {
    const shown = oneOfEach([
      entry("a"),
      entry("b", { title: "SSH brute-force attempts against 12 hosts" }),
      entry("c", { last_seen: "2026-10-03T10:00:00Z" }),
    ]);
    expect(shown.map((incident) => incident.incident_id)).toEqual(["a", "b"]);
    expect(shown[0]).toMatchObject({ occurrences: 2, last_seen: "2026-10-03T10:00:00Z" });
  });

  it("keeps an approved incident apart from a sample that reads the same", () => {
    expect(oneOfEach([entry("a"), entry("b", { source: "run", synthetic: false })])).toHaveLength(
      2,
    );
  });
});
