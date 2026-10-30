import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Delivery } from "@/lib/api/types";

import { canSendAgain, Deliveries } from "./deliveries";

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

  it("says a delivery was never confirmed after the run ended, and offers to send it again", () => {
    renderCard([delivery("approved"), delivery("sent")], true);
    expect(screen.getByText(/Delivery not confirmed/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Send again" })).toHaveLength(1);
  });
});
