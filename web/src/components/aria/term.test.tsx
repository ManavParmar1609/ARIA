import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GLOSSARY } from "@/lib/glossary";

import { Term } from "./term";

describe("term", () => {
  it("opens its own definition with the browser's popover, no script", () => {
    const { container } = render(
      <p>
        Safety <Term name="safety-floor">floors</Term> stop a pattern being rated too low.
      </p>,
    );
    const button = screen.getByRole("button", { name: "floors" });
    expect(button.getAttribute("popovertarget")).toBe("term-safety-floor");
    const card = container.querySelector("#term-safety-floor");
    expect(card?.getAttribute("popover")).toBe("auto");
    expect(card?.textContent).toContain(GLOSSARY["safety-floor"].definition);
  });

  it("keeps ids apart when a term appears twice on a page", () => {
    render(
      <>
        <Term name="fork" />
        <Term name="fork" instance="intro" />
      </>,
    );
    const targets = screen
      .getAllByRole("button", { name: "fork" })
      .map((b) => b.getAttribute("popovertarget"));
    expect(targets).toEqual(["term-fork", "term-fork-intro"]);
  });

  it("defines every term in plain sentences", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.definition).toMatch(/^[A-Z].+\.$/);
      expect(entry.definition.length).toBeLessThan(320);
    }
  });
});
