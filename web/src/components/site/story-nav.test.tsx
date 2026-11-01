import { act, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StoryNav, StoryPager } from "./story-nav";

const route = vi.hoisted(() => ({ pathname: "/console/how-it-works" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));

/** The How ARIA works layout: the parts' navigation, the part on show, then back and next. */
function Parts({ title, hidden }: { title: string; hidden?: string }) {
  return (
    <main>
      <h1>How ARIA works</h1>
      <StoryNav />
      {hidden ? <h2>{hidden}</h2> : null}
      <section>
        <h2>{title}</h2>
        <p>The part itself.</p>
      </section>
      <StoryPager />
    </main>
  );
}

const heading = (name: string) => screen.getByRole("heading", { level: 2, name });

describe("How ARIA works, part to part", () => {
  beforeEach(() => {
    route.pathname = "/console/how-it-works";
  });

  it("leaves focus alone when a part first opens", () => {
    route.pathname = "/console/how-it-works/example";
    render(<Parts title="One incident, start to finish" />);
    expect(document.activeElement).toBe(document.body);
  });

  it("moves focus from Next to the new part's heading", () => {
    const { rerender } = render(<Parts title="What ARIA does for the person on call" />);
    act(() => screen.getByRole("link", { name: "Next: An example" }).focus());
    route.pathname = "/console/how-it-works/example";
    rerender(<Parts title="One incident, start to finish" />);
    const title = heading("One incident, start to finish");
    expect(document.activeElement).toBe(title);
    // Focusable by script only: Tab still goes from the heading to what follows it.
    expect(title.getAttribute("tabindex")).toBe("-1");
  });

  it("does the same from a numbered part", () => {
    route.pathname = "/console/how-it-works/example";
    const { rerender } = render(<Parts title="One incident, start to finish" />);
    const parts = screen.getByRole("navigation", { name: "Parts of How ARIA works" });
    act(() =>
      within(parts)
        .getByRole("link", { name: /The four steps/ })
        .focus(),
    );
    route.pathname = "/console/how-it-works/steps";
    rerender(<Parts title="Four steps, then a person decides" />);
    expect(document.activeElement).toBe(heading("Four steps, then a person decides"));
  });

  it("skips the heading of a part kept out of sight", () => {
    route.pathname = "/console/how-it-works/example";
    const { rerender } = render(
      <Parts title="One incident, start to finish" hidden="An earlier part" />,
    );
    // A hidden part has no boxes.
    Object.assign(heading("An earlier part"), { getClientRects: () => [] });
    route.pathname = "/console/how-it-works/steps";
    rerender(<Parts title="Four steps, then a person decides" hidden="An earlier part" />);
    expect(document.activeElement).toBe(heading("Four steps, then a person decides"));
  });

  it("leads the last part to a triage of your own", () => {
    route.pathname = "/console/how-it-works/questions";
    render(<Parts title="What people ask first" />);
    expect(screen.getByRole("link", { name: "Try it on real logs" }).getAttribute("href")).toBe(
      "/console/runs/new",
    );
  });
});
