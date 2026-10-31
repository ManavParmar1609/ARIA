import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Delivery } from "@/lib/api/types";

import { canSendAgain, Deliveries, previewNote, settingFor } from "./deliveries";

const delivery = (status: Delivery["status"]): Delivery => ({
  action_id: `act-${status}`,
  kind: "webhook",
  audience: "stakeholders",
  title: `Update (${status})`,
  status,
});

const renderCard = (deliveries: Delivery[], ended: boolean) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Deliveries runId="run-1" deliveries={deliveries} ended={ended} />
    </QueryClientProvider>,
  );

describe("Deliveries", () => {
  it("offers to send a failed message again, and an unconfirmed one once the run has ended", () => {
    expect(canSendAgain(delivery("failed"), false)).toBe(true);
    expect(canSendAgain(delivery("approved"), false)).toBe(false);
    expect(canSendAgain(delivery("approved"), true)).toBe(true);
    expect(canSendAgain(delivery("sent"), true)).toBe(false);
    expect(canSendAgain(delivery("skipped"), true)).toBe(false);
  });

  it("says a message is sending while the run is still going", () => {
    renderCard([delivery("approved")], false);
    expect(screen.getByText("Sending now.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send again" })).toBeNull();
  });

  it("shows a message no channel could take as a preview, with one note and no setting name", () => {
    const kept: Delivery = {
      ...delivery("skipped"),
      kind: "slack",
      problem: "SLACK_WEBHOOK_URL is not set",
    };
    renderCard(
      [kept, { ...delivery("skipped"), problem: "ARIA_OUTBOUND_WEBHOOK_URL is not set" }],
      true,
    );
    expect(screen.getAllByText("Preview")).toHaveLength(2);
    expect(screen.getByText(/No channel is connected on this server/)).toBeTruthy();
    expect(
      screen.getByText("Kept as a preview: Slack is not connected on this server."),
    ).toBeTruthy();
    // The setting names wait behind "Connect a channel", for people who run ARIA themselves.
    expect(screen.queryByText(/Not sent/)).toBeNull();
    expect(screen.getByText("Connect a channel")).toBeTruthy();
    expect(settingFor(kept)).toBe("SLACK_WEBHOOK_URL");
    expect(settingFor(delivery("failed"))).toBeNull();
  });

  it("names only the channels that were not connected when some messages were sent", () => {
    expect(previewNote([delivery("sent")])).toBeNull();
    expect(previewNote([delivery("sent"), { ...delivery("skipped"), kind: "slack" }])).toBe(
      "Slack is not connected on this server, so ARIA kept that message as a preview.",
    );
    expect(
      previewNote([
        delivery("sent"),
        { ...delivery("skipped"), kind: "slack" },
        { ...delivery("skipped"), kind: "teams", action_id: "a2" },
      ]),
    ).toBe(
      "Slack and Teams are not connected on this server, so ARIA kept those messages as previews.",
    );
  });

  it("says a delivery was never confirmed after the run ended, and offers to send it again", () => {
    renderCard([delivery("approved"), delivery("sent")], true);
    expect(screen.getByText(/Delivery not confirmed/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Send again" })).toHaveLength(1);
  });
});
