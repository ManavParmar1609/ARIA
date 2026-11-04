import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Faq } from "./faq";

/** The answer under a question, as text. */
const answer = (question: string) =>
  screen.getByText(question).nextElementSibling?.textContent ?? "";

describe("the questions people ask first", () => {
  it("describes severity as it is decided now: floors, a promise per level and a person", () => {
    render(<Faq />);
    const severity = answer("How does it choose a severity?");
    expect(severity).toContain("two kinds of impact");
    expect(severity).toContain("a promise for each level, tighter for SEV1 and SEV2");
    expect(severity).toContain("may only pick from that list");
    expect(answer("What if the logs are unlike anything it has seen?")).toContain(
      "never decided alone",
    );
    expect(answer("How does it learn, and how would you know it had gone wrong?")).toContain(
      "From blind checks.",
    );
  });

  it("points at the tests on unseen systems and the tuning record only when the results hold them", () => {
    const { unmount } = render(<Faq />);
    expect(answer("What if the logs are unlike anything it has seen?")).not.toContain(
      "Test results shows the result",
    );
    expect(answer("How do you know it works?")).toContain("never on the published tests");
    unmount();
    render(<Faq tested={{ unseen: true, tuned: true }} />);
    expect(answer("What if the logs are unlike anything it has seen?")).toContain(
      "Test results shows the result",
    );
    expect(answer("How do you know it works?")).toContain("untouched, looked at or tuned on");
  });

  it("keeps every answer in view, with the limits as a list", () => {
    render(<Faq />);
    expect(screen.getByRole("heading", { name: "What people ask first" })).toBeTruthy();
    expect(screen.getAllByRole("term")).toHaveLength(9);
    const limits = screen.getByText("Where does it fall short?").nextElementSibling;
    expect(limits?.querySelectorAll("li")).toHaveLength(6);
  });
});
