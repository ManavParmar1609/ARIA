import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IncidentOut } from "@/lib/api/types";
import {
  filterOptions,
  kindTitle,
  loosenAdvice,
  matches,
  mergeEntries,
  mostSeen,
  mostSeenTitle,
  mostSeenTop,
  NO_FILTERS,
  originName,
  originOf,
  percent,
  readFilters,
  readSort,
  severityBars,
  severityTitle,
  sortEntries,
  summarise,
  systemTitle,
  timeline,
  timelineTitle,
  toggled,
  topBars,
  withFilters,
  type Filters,
} from "@/lib/library";

import { Memory, oneOfEach } from "./memory";

const route = vi.hoisted(() => ({ search: "" }));
const api = vi.hoisted(() => ({
  library: [] as unknown[],
  hits: [] as unknown[],
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/console/memory",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/lib/api/hooks", () => ({
  // The whole library, and what a search finds.
  useLibrary: () => ({
    isPending: false,
    isError: false,
    data: { incidents: api.library, complete: true },
    refetch: vi.fn(),
  }),
  useIncidentSearch: (query: string) => ({
    isPending: false,
    isError: false,
    isPlaceholderData: false,
    data: query ? api.hits : undefined,
    refetch: vi.fn(),
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
    runbook_slug: "ssh-bruteforce",
    occurrences: 1,
    last_seen: "2026-10-01T10:00:00Z",
    source: "curated",
    synthetic: true,
    ...changes,
  }) as IncidentOut;

// A small library: two HDFS stories (one seen twice), a SEV3 on SSH without a runbook, and an
// approved ZooKeeper incident from real logs.
const blocks = {
  title: "DataNodes failing to serve blocks",
  system: "hdfs",
  failure_mode: "block_serve_exceptions",
  severity: "SEV1",
  resolution: "Restart the DataNode",
  runbook_slug: "hdfs-block-serve",
} as const;
const LIBRARY = [
  entry("blocks-1", { ...blocks, last_seen: "2026-10-03T10:00:00Z" }),
  entry("blocks-2", { ...blocks, last_seen: "2026-10-02T10:00:00Z" }),
  entry("lease", {
    title: "HDFS lease renewal failures",
    system: "hdfs",
    failure_mode: "hdfs_lease_renewal",
    severity: "SEV3",
    resolution: "Renew the lease",
    runbook_slug: "hdfs-lease-renewal",
    last_seen: "2026-09-20T10:00:00Z",
  }),
  entry("ssh", { severity: "SEV3", runbook_slug: null, last_seen: "2026-09-01T10:00:00Z" }),
  entry("inc-20261001-ab", {
    title: "ZooKeeper quorum lost",
    system: "zookeeper",
    failure_mode: "quorum_connection_loss",
    severity: "SEV2",
    resolution: "Restart the follower",
    runbook_slug: "zookeeper-quorum-loss",
    source: "run",
    synthetic: false,
    last_seen: "2026-10-04T10:00:00Z",
  }),
];
const ENTRIES = mergeEntries(LIBRARY);
const INCIDENTS = ENTRIES.map((e) => e.incident);
const filters = (changes: Partial<Filters>): Filters => ({ ...NO_FILTERS, ...changes });

afterEach(() => {
  route.search = "";
  api.library = [];
  api.hits = [];
});

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

  it("keeps the date of every sighting it merges", () => {
    expect(ENTRIES[0]?.seen).toEqual([
      { when: "2026-10-03T10:00:00Z", times: 1 },
      { when: "2026-10-02T10:00:00Z", times: 1 },
    ]);
  });
});

describe("filtering the incident library", () => {
  it("reads filters from the address, repeated or comma-separated, and drops unknown levels", () => {
    const read = readFilters(
      new URLSearchParams(
        "sev=SEV2,sev1&sev=SEV9&system=hdfs&system=bgl&kind=bruteforce&from=sample&runbook=1",
      ),
    );
    expect(read).toEqual({
      severity: ["SEV1", "SEV2"],
      system: ["bgl", "hdfs"],
      kind: ["bruteforce"],
      origin: ["sample"],
      runbook: true,
    });
    expect(readFilters(new URLSearchParams(""))).toEqual(NO_FILTERS);
  });

  it("writes filters back to the address, leaving the search and the order alone", () => {
    const next = withFilters(
      "q=disk&sort=seen&sev=SEV4",
      filters({ severity: ["SEV1"], system: ["hdfs"], runbook: true }),
    );
    expect(next).toBe("q=disk&sort=seen&sev=SEV1&system=hdfs&runbook=1");
    expect(withFilters(next, NO_FILTERS)).toBe("q=disk&sort=seen");
  });

  it("switches one value on and off, keeping the levels in order", () => {
    const on = toggled(filters({ severity: ["SEV3"] }), "severity", "SEV1");
    expect(on.severity).toEqual(["SEV1", "SEV3"]);
    expect(toggled(on, "severity", "SEV3").severity).toEqual(["SEV1"]);
  });

  it("matches any value within a filter and every filter together", () => {
    const zk = INCIDENTS.find((i) => i.system === "zookeeper");
    if (!zk) throw new Error("fixture");
    expect(matches(zk, filters({ severity: ["SEV1", "SEV2"] }))).toBe(true);
    expect(matches(zk, filters({ severity: ["SEV2"], system: ["hdfs"] }))).toBe(false);
    // Leaving one filter out, as each option's count does.
    expect(matches(zk, filters({ severity: ["SEV2"], system: ["hdfs"] }), "system")).toBe(true);
    const ssh = INCIDENTS.find((i) => i.system === "openssh");
    if (!ssh) throw new Error("fixture");
    expect(matches(ssh, filters({ runbook: true }))).toBe(false);
  });

  it("counts each option with the other filters on but not its own", () => {
    const chosen = filters({ severity: ["SEV1"], system: ["hdfs"] });
    const levels = filterOptions(INCIDENTS, chosen, "severity");
    // HDFS holds one SEV1 story and one SEV3; the SEV3 count ignores the SEV1 choice.
    expect(levels.map((o) => [o.value, o.count, o.chosen])).toEqual([
      ["SEV1", 1, true],
      ["SEV2", 0, false],
      ["SEV3", 1, false],
      ["SEV4", 0, false],
    ]);
    const systems = filterOptions(INCIDENTS, chosen, "system");
    expect(systems.map((o) => [o.name, o.count])).toEqual([
      ["HDFS", 1],
      ["OpenSSH", 0],
      ["ZooKeeper", 0],
    ]);
  });

  it("names where an incident came from in plain words", () => {
    expect(INCIDENTS.map((i) => originName(originOf(i)))).toEqual([
      "Built from a sample",
      "Built from a sample",
      "Built from a sample",
      "Approved triage of real logs",
    ]);
    expect(originName(originOf(entry("x", { source: "run", synthetic: true })))).toBe(
      "Approved triage of a sample",
    );
  });

  it("says which filter to loosen when nothing matches", () => {
    // Without the system filter two SEV3 incidents match; without the level, only one.
    const none = filters({ severity: ["SEV3"], system: ["zookeeper"] });
    expect(INCIDENTS.filter((i) => matches(i, none))).toHaveLength(0);
    expect(loosenAdvice(INCIDENTS, none)).toBe("Loosen “System”: 2 incidents match without it.");
    expect(loosenAdvice(INCIDENTS, NO_FILTERS)).toBeNull();
  });

  it("orders by most recent, most seen and most serious", () => {
    const ids = (sort: "recent" | "seen" | "serious") =>
      sortEntries(ENTRIES, sort).map((e) => e.incident.incident_id);
    expect(ids("recent")).toEqual(["inc-20261001-ab", "blocks-1", "lease", "ssh"]);
    expect(ids("seen")[0]).toBe("blocks-1");
    expect(ids("serious")).toEqual(["blocks-1", "inc-20261001-ab", "lease", "ssh"]);
  });

  it("reads the order from the address, closest first while searching", () => {
    expect(readSort(new URLSearchParams(""), false)).toBe("recent");
    expect(readSort(new URLSearchParams(""), true)).toBe("closest");
    expect(readSort(new URLSearchParams("sort=seen"), true)).toBe("seen");
    expect(readSort(new URLSearchParams("sort=closest"), false)).toBe("recent");
  });
});

describe("summing up the incident library", () => {
  it("counts incidents, sightings, systems and the share with a runbook", () => {
    expect(summarise(ENTRIES)).toEqual({
      incidents: 4,
      sightings: 5,
      systems: 3,
      withRunbook: 0.75,
    });
    expect(percent(0.004)).toBe("1%");
    expect(percent(0.996)).toBe("99%");
    expect(percent(1)).toBe("100%");
  });

  it("titles the levels with what the mix says", () => {
    expect(severityTitle(severityBars(ENTRIES, NO_FILTERS))).toBe("SEV3 is the most common level");
    const sev3 = mergeEntries([entry("a", { severity: "SEV3" }), entry("b", { title: "Other" })]);
    expect(severityTitle(severityBars(sev3, NO_FILTERS))).toBe(
      "SEV2 and SEV3 are the most common levels",
    );
    const most = mergeEntries([
      entry("a", { severity: "SEV3" }),
      entry("b", { severity: "SEV3", title: "B" }),
      entry("c", { title: "C" }),
    ]);
    expect(severityTitle(severityBars(most, NO_FILTERS))).toBe("Most incidents here are SEV3");
    expect(severityTitle(severityBars(ENTRIES, filters({ severity: ["SEV1", "SEV2"] })))).toBe(
      "2 of the 4 incidents here are SEV1 or SEV2",
    );
  });

  it("ranks systems and kinds, folding the rest and keeping a chosen one", () => {
    const many = mergeEntries(
      ["bgl", "bgl", "bgl", "hpc", "hpc", "hdfs", "linux", "mac", "apache", "android", "spark"].map(
        (system, index) => entry(`e${index}`, { system, title: `Story ${index}` }),
      ),
    );
    const set = topBars(many, filters({ system: ["spark"] }), "system", 3);
    expect(set.bars.map((bar) => [bar.name, bar.count, bar.chosen])).toEqual([
      ["BlueGene/L", 3, false],
      ["HPC", 2, false],
      ["Android", 1, false],
      ["Spark", 1, true],
      ["4 other systems", 4, false],
    ]);
    expect(set.bars.at(-1)?.members?.map((m) => m.name)).toEqual([
      "Apache",
      "HDFS",
      "Linux",
      "macOS",
    ]);
    expect(systemTitle(set)).toBe("1 of the 11 incidents here comes from Spark");
    // A lone leftover keeps its own name.
    expect(topBars(ENTRIES, NO_FILTERS, "system", 2).bars.map((bar) => bar.name)).toEqual([
      "HDFS",
      "OpenSSH",
      "ZooKeeper",
    ]);
    expect(systemTitle(topBars(ENTRIES, NO_FILTERS, "system"))).toBe("HDFS has the most incidents");
    expect(kindTitle(topBars(ENTRIES, NO_FILTERS, "kind"))).toBe(
      "4 kinds of failure tie for the most, with 1 incident each",
    );
    expect(kindTitle(topBars(ENTRIES, filters({ kind: ["bruteforce"] }), "kind"))).toBe(
      "1 of the 4 incidents here shows brute-force attempts",
    );
  });

  it("ranks the most seen, with the whole tie for first when it is a few more", () => {
    const repeats = mostSeen(ENTRIES);
    expect(repeats.map((e) => e.incident.incident_id)).toEqual(["blocks-1"]);
    expect(mostSeenTitle(repeats)).toBe(
      "Seen most often, 2 times: DataNodes failing to serve blocks",
    );
    const twice = mergeEntries(
      Array.from({ length: 7 }, (_, index) =>
        entry(`t${index}`, { title: `Story ${index}`, occurrences: 2 }),
      ),
    );
    expect(mostSeenTop(mostSeen(twice))).toHaveLength(7);
    expect(mostSeenTitle(mostSeen(twice))).toBe("7 incidents were seen most often, 2 times each");
  });

  it("charts sightings over time only when they fall on enough days", () => {
    const twoDays = [entry("a"), entry("b", { title: "B", last_seen: "2026-10-05T08:00:00Z" })];
    expect(timeline(mergeEntries(twoDays))).toBeNull();
    const days = ["01", "02", "02", "04", "05", "09"].map((day, index) =>
      entry(`d${index}`, { title: `Story ${index}`, last_seen: `2026-10-${day}T08:00:00Z` }),
    );
    const line = timeline(mergeEntries(days));
    expect(line?.unit).toBe("day");
    // Every day from the first to the last, the empty ones included.
    expect(line?.buckets.map((b) => b.count)).toEqual([1, 2, 0, 1, 1, 0, 0, 0, 1]);
    expect(line && timelineTitle(line)).toBe("Sightings peaked on 2 October");
    const weeks = Array.from({ length: 6 }, (_, index) =>
      entry(`w${index}`, {
        title: `Story ${index}`,
        last_seen: new Date(Date.UTC(2026, 0, 5 + index * 14)).toISOString(),
      }),
    );
    expect(timeline(mergeEntries(weeks))?.unit).toBe("week");
  });
});

describe("the incident library page", () => {
  it("sums up the whole library in figures and charts", () => {
    api.library = LIBRARY;
    render(createElement(Memory));
    const figure = (label: string) =>
      screen.getByText(label).parentElement?.querySelector("dd .sr-only")?.textContent;
    expect(figure("incidents in the library")).toBe("4");
    expect(figure("sightings, repeats included")).toBe("5");
    expect(figure("systems covered")).toBe("3");
    expect(figure("have a runbook to follow")).toBe("75%");
    expect(screen.getByRole("heading", { name: "SEV3 is the most common level" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "HDFS has the most incidents" })).toBeTruthy();
    // Every chart has a table with the same figures.
    const levels = screen.getByRole("region", { name: "SEV3 is the most common level" });
    fireEvent.click(within(levels).getByRole("button", { name: /^Show as a table/ }));
    const table = within(levels).getByRole("table", { name: "Incidents by severity level" });
    expect(within(table).getByRole("rowheader", { name: "SEV3, moderate" })).toBeTruthy();
    expect(screen.getByText(/^4 incidents in the library, most recent first/)).toBeTruthy();
  });

  it("filters from a chart, and keeps the filter in the address so Back undoes it", () => {
    api.library = LIBRARY;
    const push = vi.spyOn(window.history, "pushState").mockImplementation(() => undefined);
    render(createElement(Memory));
    const levels = screen.getByRole("region", { name: "SEV3 is the most common level" });
    fireEvent.click(within(levels).getByRole("button", { name: /^SEV1 critical/ }));
    expect(push).toHaveBeenLastCalledWith(null, "", "/console/memory?sev=SEV1");
    const systems = screen.getByRole("region", { name: "HDFS has the most incidents" });
    fireEvent.click(within(systems).getByRole("button", { name: /^ZooKeeper/ }));
    expect(push).toHaveBeenLastCalledWith(null, "", "/console/memory?system=zookeeper");
  });

  it("shows a filtered library, with each chip pressed and a way to clear them all", () => {
    api.library = LIBRARY;
    route.search = "q=disk&sev=SEV1&sev=SEV2&system=hdfs";
    api.hits = [LIBRARY[0]];
    const push = vi.spyOn(window.history, "pushState").mockImplementation(() => undefined);
    render(createElement(Memory));
    const chip = screen.getByRole("button", { name: "SEV1 critical 1 incident" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(
      screen.getByRole("button", { name: "SEV3 moderate 1 incident" }).getAttribute("aria-pressed"),
    ).toBe("false");
    expect(screen.getByText("incident matches your filters")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "1 of the 2 incidents here is SEV1 or SEV2" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(push).toHaveBeenLastCalledWith(null, "", "/console/memory?q=disk");
  });

  it("says which filter to loosen when nothing matches, and loosens it", () => {
    api.library = LIBRARY;
    route.search = "sev=SEV3&system=zookeeper";
    const push = vi.spyOn(window.history, "pushState").mockImplementation(() => undefined);
    render(createElement(Memory));
    expect(screen.getByText("No incident matches these filters")).toBeTruthy();
    expect(screen.getByText("Loosen “System”: 2 incidents match without it.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear “System”" }));
    expect(push).toHaveBeenLastCalledWith(null, "", "/console/memory?sev=SEV3");
  });

  it("brings a search back into the box on Back", () => {
    api.library = LIBRARY;
    route.search = "q=disk";
    render(createElement(Memory));
    const box = screen.getByRole<HTMLInputElement>("searchbox", { name: "Search" });
    expect(box.value).toBe("disk");
    act(() => {
      window.history.replaceState(null, "", "/console/memory?q=quorum");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(box.value).toBe("quorum");
    window.history.replaceState(null, "", "/");
  });
});

describe("searching the incident library", () => {
  it("says once that nothing matches a search, and how to widen it", () => {
    api.library = LIBRARY;
    route.search = "q=qqzzxx";
    render(createElement(Memory));
    const said = screen.getAllByText(/qqzzxx/);
    expect(said.map((element) => element.textContent)).toEqual([
      'No past incident matches "qqzzxx"',
    ]);
    const empty = screen.getByText("Try fewer or different words.");
    // In the live region, so a screen reader hears it as the results change.
    expect(said[0]?.closest("[aria-live]")).not.toBeNull();
    // No filter is on, so the advice is about the words alone.
    expect(empty.closest("[aria-live]")?.textContent).not.toMatch(/filter/i);
  });

  it("names the filter to loosen when the search finds incidents the filters hide", () => {
    api.library = LIBRARY;
    api.hits = [LIBRARY[4]];
    route.search = "q=quorum&system=openssh";
    render(createElement(Memory));
    expect(screen.getByText('No incident close to "quorum" matches your filters')).toBeTruthy();
    expect(screen.getByText("Loosen “System”: 1 incident matches without it.")).toBeTruthy();
  });

  it("lists the closest incidents that pass the filters, closest first", () => {
    api.library = LIBRARY;
    api.hits = [LIBRARY[3], LIBRARY[2], LIBRARY[0]];
    route.search = "q=disk&system=hdfs";
    render(createElement(Memory));
    expect(
      screen.getByText(
        /^The 2 closest incidents to "disk", by keyword and by meaning, among those that match your filters, closest first/,
      ),
    ).toBeTruthy();
    const titles = [...document.querySelectorAll("details summary")].map(
      (summary) => summary.textContent,
    );
    expect(titles[0]).toContain("HDFS lease renewal failures");
    expect(titles[1]).toContain("DataNodes failing to serve blocks");
  });
});
