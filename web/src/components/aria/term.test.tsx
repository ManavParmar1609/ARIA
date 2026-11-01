import { act, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { GLOSSARY, glossaryMentions } from "@/lib/glossary";
import { LEVEL_RESPONSE } from "@/lib/levels";

import { Term, TermsIn } from "./term";

/** The browser's toggle events, which happy-dom does not fire on its own. */
function toggle(card: Element, newState: "open" | "closed") {
  for (const type of ["beforetoggle", "toggle"]) {
    const event = new Event(type);
    Object.defineProperty(event, "newState", { value: newState });
    act(() => {
      card.dispatchEvent(event);
    });
  }
}

describe("term", () => {
  it("opens its own definition with the browser's popover", () => {
    const { container } = render(
      <p>
        Safety <Term name="safety-floor">floors</Term> stop a pattern being rated too low.
      </p>,
    );
    const button = screen.getByRole("button", { name: "floors" });
    expect(button.getAttribute("popovertarget")).toBe("term-safety-floor");
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    const card = container.querySelector("#term-safety-floor");
    expect(card?.getAttribute("popover")).toBe("auto");
    expect(card?.textContent).toContain(GLOSSARY["safety-floor"].definition);
  });

  it("names the card after the term and describes it with the definition", () => {
    render(<Term name="safety-floor">floors</Term>);
    const card = screen.getByRole("dialog", { name: "Safety floor", hidden: true });
    const description = document.getElementById(card.getAttribute("aria-describedby") ?? "");
    expect(description?.textContent).toBe(GLOSSARY["safety-floor"].definition);
  });

  it("anchors the card to its word", () => {
    const html = renderToStaticMarkup(<Term name="fork" instance="a.b" />);
    // A dashed ident: the instance's dot would not make one.
    expect(html).toContain('style="anchor-name:--term-fork-a-b"');
    expect(html).toContain('style="position-anchor:--term-fork-a-b"');
  });

  it("moves focus into the card as it opens, and closes it once focus moves past", () => {
    render(
      <>
        <p>
          A <Term name="runbook" />.
        </p>
        <button type="button">Next thing</button>
      </>,
    );
    const card = screen.getByRole("dialog", { hidden: true });
    const hide = vi.fn();
    Object.assign(card, { hidePopover: hide });
    toggle(card, "open");
    expect(document.activeElement).toBe(card);

    // Within the card, to its Close button: it stays open.
    act(() => screen.getByRole("button", { name: "Close", hidden: true }).focus());
    expect(hide).not.toHaveBeenCalled();
    // Past it: it closes, so it never covers what Tab reaches next.
    act(() => screen.getByRole("button", { name: "Next thing" }).focus());
    expect(hide).toHaveBeenCalledTimes(1);
  });

  it("leaves a closing card to the browser, which hands focus back to the word", () => {
    render(<Term name="runbook" />);
    const card = screen.getByRole("dialog", { hidden: true });
    const hide = vi.fn();
    Object.assign(card, { hidePopover: hide });
    toggle(card, "open");
    // Escape: the browser hides the card, then focuses the word.
    toggle(card, "closed");
    fireEvent.blur(card, { relatedTarget: screen.getByRole("button", { name: "runbook" }) });
    expect(hide).not.toHaveBeenCalled();
  });

  it("keeps ids apart when a term appears twice on a page", () => {
    render(
      <>
        <Term name="fork" />
        <Term name="fork" instance="intro" />
      </>,
    );
    const targets = screen
      .getAllByRole("button", { name: /\(fork\)/ })
      .map((b) => b.getAttribute("popovertarget"));
    expect(targets).toEqual(["term-fork", "term-fork-intro"]);
  });

  it("defines every term in plain sentences", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.definition).toMatch(/^[A-Z].+\.$/);
      expect(entry.definition.length).toBeLessThan(320);
    }
  });

  it("defines the severity levels in the words the report uses", () => {
    expect(GLOSSARY.sev1.term).toBe("SEV1 (critical)");
    expect(GLOSSARY.sev3.definition).toContain(LEVEL_RESPONSE.SEV3);
    expect(GLOSSARY.sev4.definition).toContain(LEVEL_RESPONSE.SEV4);
  });
});

describe("terms in text from data", () => {
  /** The words that open a definition, leaving out each card's Close button. */
  const words = () =>
    screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("aria-haspopup"))
      .map((b) => b.textContent);

  it("defines the first mention of each word, as written", () => {
    const { container } = render(
      <p>
        <TermsIn
          text="DataNodes failing to serve blocks in HDFS, and more DataNodes after"
          instance="card"
        />
      </p>,
    );
    expect(words()).toEqual(["DataNodes", "HDFS"]);
    expect(container.querySelector("#term-datanode-card")).not.toBeNull();
    // The words around them stay as they were.
    expect(container.textContent).toContain(" failing to serve blocks in ");
    expect(container.textContent).toContain(", and more DataNodes after");
  });

  it("keeps punctuation touching a word on the word's line", () => {
    const { container } = render(
      <TermsIn text='as in the past incident "DataNodes failing" (HDFS).' instance="claim" />,
    );
    const [datanodes, hdfs] = words().map((word) =>
      screen.getByRole("button", { name: word ?? "" }),
    );
    expect(datanodes?.parentElement?.className).toBe("whitespace-nowrap");
    expect(datanodes?.previousSibling?.textContent).toBe('"');
    expect(hdfs?.previousSibling?.textContent).toBe("(");
    expect(hdfs?.parentElement?.lastChild?.textContent).toBe(").");
    // Nothing is lost or repeated around them.
    const shown = container.cloneNode(true) as HTMLElement;
    shown.querySelectorAll("[popover]").forEach((card) => card.remove());
    expect(shown.textContent).toBe('as in the past incident "DataNodes failing" (HDFS).');
  });

  it("skips words already defined nearby, and leaves plain text alone", () => {
    render(<TermsIn text="BlueGene/L and Lustre" instance="tech" skip={["lustre"]} />);
    expect(words()).toEqual(["BlueGene/L"]);
    const { container } = render(<TermsIn text="A web server's error log" instance="plain" />);
    expect(container.querySelector("button")).toBeNull();
  });

  it("finds whole words only, and never two in the same letters", () => {
    expect(glossaryMentions("Kernel panics stop nodes; I/O nodes fail to mount Lustre.")).toEqual([
      { start: 0, end: 13, key: "kernel-panic" },
      { start: 26, end: 35, key: "io-node" },
      { start: 50, end: 56, key: "lustre" },
    ]);
    expect(glossaryMentions("A Hadoop file system (HDFS)").map((m) => m.key)).toEqual([
      "hadoop",
      "hdfs",
    ]);
    expect(glossaryMentions("HDFSx and OpenSSHd")).toEqual([]);
  });
});
