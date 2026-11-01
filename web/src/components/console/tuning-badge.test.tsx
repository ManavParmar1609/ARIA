import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GLOSSARY } from "@/lib/glossary";

import { TuningBadge } from "./tuning-badge";

const description = (card: HTMLElement) =>
  document.getElementById(card.getAttribute("aria-describedby") ?? "")?.textContent;

// The badge's name is its label, then the test's name for screen readers. (The test DOM puts a
// space between the two spans; a browser joins them as written.)
const badge = (label: string, test: string) =>
  screen.getByRole("button", { name: new RegExp(`^${label} ?: ${test}$`) });

describe("a tuning badge", () => {
  it("names the test it belongs to, so a list of the page's buttons tells them apart", () => {
    render(
      <TuningBadge
        id="ev-jira"
        tuning={{ status: "seen", since: "2026-11-01", note: "Scored once." }}
        context="Jira issues with priorities people set"
      />,
    );
    const button = badge("Looked at", "Jira issues with priorities people set");
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    expect(button.getAttribute("popovertarget")).toBe("tuning-ev-jira");
  });

  it("opens a card named for its status and date, with what it means and the record's note", () => {
    render(
      <TuningBadge
        id="ev-hadoop"
        tuning={{ status: "tuned", since: "2026-11-01", note: "A rule changed after these jobs." }}
        context="Hadoop jobs"
      />,
    );
    badge("Tuned since 2026-11-01", "Hadoop jobs");
    const card = screen.getByRole("dialog", { name: "Tuned since 2026-11-01", hidden: true });
    expect(card.getAttribute("popover")).toBe("auto");
    expect(description(card)).toBe(`${GLOSSARY.tuned.definition} A rule changed after these jobs.`);
  });

  it("gives a looked-at test's date only in its card", () => {
    render(
      <TuningBadge
        id="ev-ait-ads"
        tuning={{ status: "seen", since: "2026-11-01", note: "" }}
        context="Security alerts"
      />,
    );
    badge("Looked at", "Security alerts");
    const card = screen.getByRole("dialog", { name: "Looked at since 2026-11-01", hidden: true });
    expect(description(card)?.trim()).toBe(GLOSSARY["looked-at"].definition);
  });
});
