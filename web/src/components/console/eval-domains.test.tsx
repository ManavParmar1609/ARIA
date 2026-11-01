import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readDomains, type NewDomains } from "@/lib/domains";
import { EVAL_DOC_URL } from "@/lib/site-data";
import { readTuning } from "@/lib/tuning";
import * as raw from "@/test/domains";

import { DOMAIN_CARDS, domainSummary, writeUpAnchor } from "./domain-results";
import { NewDomainCards } from "./eval-domains";
import { contents } from "./evals";

const domains = (summaries: unknown = raw.domains()) => readDomains(summaries) as NewDomains;
const titles = () =>
  screen.getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent);
/** The words as they read on the page, without the definition cards their dotted words open. */
function shown(element: HTMLElement): string {
  const copy = element.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("[popover]").forEach((card) => card.remove());
  return copy.textContent ?? "";
}

describe("the new-domain cards", () => {
  it("shows a card for each suite, in the write-up's order, under its own heading", () => {
    render(<NewDomainCards domains={domains()} />);
    expect(screen.getByRole("heading", { level: 3, name: "New kinds of data" })).toBeTruthy();
    expect(titles()).toEqual([
      "Security alerts from attacked networks",
      "Microservice shops with injected code faults",
      "Microservice systems with injected anomalies",
      "Kubernetes incidents",
      "Jira issues with priorities people set",
      "Faults injected into an online shop's pods",
    ]);
    // The introduction says what the tests measure, since none of the data labels severity.
    expect(shown(screen.getByText(/None of them labels severity/))).toContain(
      "whether ARIA notices a problem, ranks it above routine noise, names the service at fault and sets a ticket's priority.",
    );
  });

  it("opens each card with its verdict and its shortfall, and links it to the write-up", () => {
    render(<NewDomainCards domains={domains()} />);
    for (const result of domains().results) {
      const { title, heading } = DOMAIN_CARDS[result.key];
      const card = screen.getByRole("region", { name: title });
      const { verdict, shortfall } = domainSummary(result);
      expect(within(card).getByText(verdict)).toBeTruthy();
      expect(card.textContent).toContain(`Where it falls short: ${shortfall}`);
      const link = within(card).getByRole("link", { name: new RegExp(`write-up ?: ${title}$`) });
      expect(link.getAttribute("href")).toBe(`${EVAL_DOC_URL}${writeUpAnchor(heading)}`);
    }
  });

  it("badges a card the tuning record knows, and only those", () => {
    render(<NewDomainCards domains={domains()} tuning={readTuning(raw.registry())} />);
    const alerts = screen.getByRole("region", { name: DOMAIN_CARDS["ait-ads"].title });
    expect(
      within(alerts).getByRole("button", { name: /^Looked at ?: Security alerts/ }),
    ).toBeTruthy();
    // The record in the fixtures has no entry for the code faults: no badge, rather than a guess.
    const faults = screen.getByRole("region", { name: DOMAIN_CARDS.rcaeval.title });
    expect(
      within(faults).queryByRole("button", { name: /^(Looked at|Tuned|Untouched)/ }),
    ).toBeNull();
  });

  it("names the suites not run yet, and shows no card for them", () => {
    const missing = { missing: "download it with: aria data download --source itbench-lite" };
    render(<NewDomainCards domains={domains({ ...raw.domains(), itbench: missing })} />);
    expect(titles()).not.toContain("Kubernetes incidents");
    expect(screen.getByText(/^Not run yet: Kubernetes incidents\./)).toBeTruthy();
  });

  it("shows only the line saying so when no suite has run", () => {
    render(<NewDomainCards domains={domains({ jira: { missing: "download it" } })} />);
    expect(screen.queryAllByRole("heading", { level: 4 })).toEqual([]);
    expect(screen.queryByText(/None of them labels severity/)).toBeNull();
    expect(screen.getByText(/^Not run yet: Jira priorities\./)).toBeTruthy();
  });
});

describe("the contents of Test results", () => {
  const realData = (toc: ReturnType<typeof contents>) =>
    toc.find((item) => item.id === "ev-real-data")?.children?.map((child) => child.label);

  it("lists the new-domain cards after the other tests on real data, when they have run", () => {
    const labels = realData(contents(true, true, false, domains().results));
    expect(labels?.slice(-6)).toEqual([
      "Security alerts",
      "Microservice code faults",
      "Microservice anomalies",
      "Kubernetes incidents",
      "Jira priorities",
      "Online shop pod faults",
    ]);
    expect(labels?.[0]).toBe("Hadoop file system blocks");
  });

  it("lists none of them while the results have none", () => {
    expect(realData(contents(true, true, false))).toHaveLength(9);
  });
});
