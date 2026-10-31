import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import type { IncidentOut } from "@/lib/api/types";

import { Memory, oneOfEach } from "./memory";

const route = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/console/memory",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ replace: vi.fn() }),
}));
vi.mock("@/lib/api/hooks", () => ({
  // A search finds nothing; the whole library holds one incident.
  useIncidents: (query?: string, system?: string) => ({
    isPending: false,
    isError: false,
    isPlaceholderData: false,
    data: query || system ? [] : [entry("a")],
  }),
  useSettingsView: () => ({ data: undefined }),
}));

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

describe("searching the incident library", () => {
  it("says once that nothing matches a search, and how to widen it", () => {
    route.search = "q=qqzzxx";
    render(createElement(Memory));
    const said = screen.getAllByText(/qqzzxx/);
    expect(said.map((element) => element.textContent)).toEqual([
      'No past incident matches "qqzzxx"',
    ]);
    expect(screen.getByText("Try fewer or different words.")).toBeTruthy();
    // In the live region, so a screen reader hears it as the results change.
    expect(said[0]?.closest("[aria-live]")).not.toBeNull();
    expect(screen.queryByText(/filter/i)).toBeNull();
  });

  it("suggests every system when one is chosen", () => {
    route.search = "q=qqzzxx&system=openssh";
    render(createElement(Memory));
    expect(screen.getByText("Try fewer words, or choose All systems.")).toBeTruthy();
  });
});
