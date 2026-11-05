import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTerms, improvesWords, keepsWords, readWords, type DataTermsView } from "./data-terms";
import { keptWords } from "./settings";

const READ: DataTermsView = {
  id: "anthropic",
  company: "Anthropic",
  service: "Claude API",
  providers: ["claude"],
  uses: [
    {
      account: "API",
      improves_models: false,
      keeps_prompts: "For the term of your agreement at most.",
    },
  ],
  sources: [
    { title: "Commercial Terms", url: "https://www.anthropic.com/legal/commercial-terms" },
    { title: "Data Processing Addendum", url: "https://www.anthropic.com/legal/dpa" },
  ],
  verified: "2026-11-01",
  notes: null,
};

const UNREAD: DataTermsView = {
  id: "google",
  company: "Google",
  service: "Gemini API",
  providers: ["gemini", "gemma"],
  uses: [{ account: "Free tier" }, { account: "Paid tier" }],
  sources: [{ title: "Gemini API terms", url: "https://ai.google.dev/gemini-api/terms" }],
  verified: null,
  notes: "Not verified: the page could not be reached.",
};

describe("what providers do with prompts", () => {
  it("says what terms someone read say, and when they read them", () => {
    render(<DataTerms terms={[READ, UNREAD]} />);
    const [anthropic, google] = screen.getAllByRole("listitem");
    expect(within(anthropic!).getByRole("heading").textContent).toBe("Anthropic, Claude API");
    expect(within(anthropic!).getByText("Read on 1 November 2026")).toBeTruthy();
    expect(within(anthropic!).getByText("No")).toBeTruthy();
    expect(within(anthropic!).getByText("For the term of your agreement at most.")).toBeTruthy();
    const link = within(anthropic!).getByRole("link", { name: /^Commercial Terms/ });
    expect(link.getAttribute("href")).toBe("https://www.anthropic.com/legal/commercial-terms");
    expect(link.textContent).toContain("(opens in a new tab)");
    // Terms nobody read claim nothing: every point says "Not verified", tier by tier.
    expect(within(google!).getAllByText("Not verified")).toHaveLength(5);
    expect(within(google!).getByText("Not verified: the page could not be reached.")).toBeTruthy();
  });

  it("says when the configuration records no terms", () => {
    render(<DataTerms terms={[]} />);
    expect(screen.getByText(/records no provider terms/)).toBeTruthy();
  });

  it("words each point plainly", () => {
    expect(improvesWords({ improves_models: true })).toBe("Yes, it may");
    expect(improvesWords({ improves_models: false })).toBe("No");
    expect(improvesWords({})).toBe("Not verified");
    expect(keepsWords({ keeps_prompts: null })).toBe("Not verified");
    expect(readWords(null)).toBe("Not verified");
    // A calendar date reads the same in every time zone.
    expect(readWords("2026-01-01")).toBe("Read on 1 January 2026");
  });
});

describe("keptWords", () => {
  it("says runs are kept until deleted while retention is off", () => {
    expect(keptWords({ days: 0, purge_interval_s: 0 })).toBe("Until someone deletes them");
    expect(keptWords(undefined)).toBe("Until someone deletes them");
  });

  it("says how long runs are kept and how they are purged", () => {
    expect(keptWords({ days: 90, purge_interval_s: 3600 })).toBe(
      "90 days after their last change, purged every hour",
    );
    expect(keptWords({ days: 1, purge_interval_s: 172_800 })).toBe(
      "1 day after their last change, purged every 2 days",
    );
    expect(keptWords({ days: 30, purge_interval_s: 0 })).toBe(
      "30 days after their last change, purged when someone runs aria purge",
    );
  });
});
