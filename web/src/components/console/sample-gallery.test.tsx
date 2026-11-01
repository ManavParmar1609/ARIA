import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Scenario } from "@/lib/api/types";

import { SampleGallery } from "./sample-gallery";

const route = vi.hoisted(() => ({ search: "" }));
const SAMPLES = vi.hoisted(
  () =>
    [
      {
        id: "hdfs.block_serve_exceptions",
        system: "hdfs",
        source: "bigdata",
        source_name: "Big-data clusters",
        title: "Storage servers stop handing out data",
        technology: "HDFS",
        summary: "DataNodes fail while serving blocks of data.",
        headline: true,
        benign: false,
      },
      {
        id: "openssh.bruteforce",
        system: "openssh",
        source: "security",
        source_name: "Security and sign-ins",
        title: "Someone keeps guessing passwords",
        technology: "OpenSSH",
        summary: "Failed logins from many addresses.",
        headline: true,
        benign: false,
      },
    ] as unknown as Scenario[],
);

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/runs/new",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/hooks", () => ({
  useScenarios: () => ({ isPending: false, isError: false, data: SAMPLES }),
  useRealIncidents: () => ({ isPending: false, data: [] }),
  useStartSample: () => ({ isPending: false, mutate: vi.fn() }),
  useReplay: () => ({ isPending: false, mutate: vi.fn() }),
}));

describe("choosing where the logs come from", () => {
  beforeEach(() => {
    route.search = "";
  });

  it("leaves focus alone when the page opens on a chosen log", () => {
    route.search = "log=hdfs";
    render(<SampleGallery />);
    expect(screen.getByRole("heading", { level: 2, name: "HDFS" })).toBeTruthy();
    expect(document.activeElement).toBe(document.body);
  });

  it("moves focus to the log's issues, and back to its tile from All logs", () => {
    const { rerender } = render(<SampleGallery />);
    const tile = screen.getByRole("link", { name: /^HDFS/ });
    act(() => tile.focus());

    route.search = "log=hdfs";
    rerender(<SampleGallery />);
    const issues = screen.getByRole("heading", { level: 2, name: "HDFS" });
    expect(document.activeElement).toBe(issues);
    expect(issues.getAttribute("tabindex")).toBe("-1");

    route.search = "";
    rerender(<SampleGallery />);
    expect(document.activeElement).toBe(screen.getByRole("link", { name: /^HDFS/ }));
  });

  it("defines a sample's system and jargon in plain words, once per card", () => {
    route.search = "log=hdfs";
    render(<SampleGallery />);
    const words = screen
      .getAllByRole("button")
      .filter((button) => button.hasAttribute("aria-haspopup"))
      .map((button) => button.textContent);
    expect(words).toEqual(["HDFS", "DataNodes"]);
  });
});
