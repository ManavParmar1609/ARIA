import { describe, expect, it } from "vitest";

import type { Delivery, OutboundAction } from "@/lib/api/types";

import { receiptText, type ReceiptFacts } from "./receipt";

const action = (id: string, kind: OutboundAction["kind"] = "slack"): OutboundAction => ({
  action_id: id,
  kind,
  audience: "responders",
  title: "SEV2: storage servers stop handing out data",
  body: "",
  status: "rejected",
  requires_approval: true,
  evidence_ids: [],
});

const delivery = (id: string, status: Delivery["status"]): Delivery =>
  ({ action_id: id, kind: "slack", audience: "responders", title: "", status }) as Delivery;

const facts = (changes: Partial<ReceiptFacts> = {}): ReceiptFacts => ({
  status: "published",
  decision: "approve",
  reviewer: "anonymous",
  you: true,
  at: "2026-10-31T00:42:00Z",
  actions: [action("a1"), action("a2", "status_page"), action("a3", "ticket_draft")],
  deliveries: [],
  connected: () => false,
  ...changes,
});

describe("receiptText", () => {
  it("says who approved, and that the messages stayed previews with no channel", () => {
    const text = receiptText(facts());
    expect(text.decision).toMatch(/^Drafted by ARIA, approved by you at \d\d:\d\d\.$/);
    expect(text.messages).toBe("3 draft messages kept here, unsent (no channel is connected).");
  });

  it("counts what was sent, what failed and what was not chosen", () => {
    const text = receiptText(
      facts({
        connected: () => true,
        deliveries: [delivery("a1", "sent"), delivery("a2", "failed")],
      }),
    );
    expect(text.messages).toBe(
      "1 message sent, 1 message not delivered (see below), 1 draft message kept here, unsent (not chosen).",
    );
  });

  it("names another reviewer, an edit and a discarded draft", () => {
    expect(
      receiptText(facts({ reviewer: "alice", you: false, decision: "edit" })).decision,
    ).toMatch(/^Drafted by ARIA, edited and approved by alice at /);
    const discarded = receiptText(facts({ status: "rejected", decision: "reject" }));
    expect(discarded.decision).toMatch(/^Drafted by ARIA, discarded by you at /);
    expect(discarded.messages).toBe("Nothing was sent.");
  });

  it("says when nobody was asked", () => {
    expect(receiptText(facts({ reviewer: "aria:auto", you: false, actions: [] }))).toEqual({
      decision: expect.stringMatching(/without review: approval was off for this incident\.$/),
      messages: null,
    });
  });
});
