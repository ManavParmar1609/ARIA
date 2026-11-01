import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { RunbookOut } from "@/lib/api/types";

import { RunbookDetail } from "./runbooks";

const answer = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("@/lib/api/hooks", () => ({ useRunbook: () => answer.current }));

const RUNBOOK: RunbookOut = {
  slug: "zookeeper-quorum-loss",
  title: "ZooKeeper quorum loss",
  when_to_use: "Peers log `Connection broken for id`.",
  systems: ["zookeeper"],
  failure_modes: ["quorum_connection_loss"],
  risk: "low",
  diagnose: [{ text: "Check which peers answer.", risk: "low" }],
  mitigate: [{ text: "Restart the peer that lost touch.", risk: "medium" }],
  verify: [{ text: "Confirm a leader is elected.", risk: "low" }],
  escalate: "",
};

describe("a runbook's page", () => {
  beforeEach(() => {
    document.title = "Runbook | ARIA console";
  });

  it("waits for the runbook before it moves focus", () => {
    answer.current = { isPending: true };
    render(<RunbookDetail slug="zookeeper-quorum-loss" />);
    expect(document.activeElement).toBe(document.body);
  });

  it("puts focus on the runbook's name once it has loaded, and names the tab after it", () => {
    answer.current = { isPending: false, isError: false, data: RUNBOOK };
    render(<RunbookDetail slug="zookeeper-quorum-loss" />);
    const title = screen.getByRole("heading", { level: 1, name: "ZooKeeper quorum loss" });
    expect(document.activeElement).toBe(title);
    expect(title.getAttribute("tabindex")).toBe("-1");
    expect(document.title).toBe("ZooKeeper quorum loss | ARIA console");
  });

  it("says so, and focuses that, when no runbook has the name", () => {
    answer.current = { isPending: false, isError: true, error: new ApiError(404, "Not found") };
    render(<RunbookDetail slug="no-such-runbook" />);
    const title = screen.getByRole("heading", { level: 1, name: "No runbook by that name" });
    expect(document.activeElement).toBe(title);
    expect(document.title).toBe("Runbook not found | ARIA console");
  });
});
