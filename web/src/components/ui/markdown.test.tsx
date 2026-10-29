import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

describe("Markdown", () => {
  it("renders Markdown but never raw HTML from logs", () => {
    const hostile = [
      "## Suspected cause",
      "",
      "**Disk full** on node-3.",
      "",
      '<script>alert("x")</script>',
      "",
      '<img src="x" onerror="alert(1)">',
      "",
      '<a href="javascript:alert(1)">click</a>',
    ].join("\n");
    const { container } = render(<Markdown>{hostile}</Markdown>);
    expect(container.querySelector("h2")?.textContent).toBe("Suspected cause");
    expect(container.querySelector("strong")?.textContent).toBe("Disk full");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });
});
