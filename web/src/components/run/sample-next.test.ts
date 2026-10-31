import { describe, expect, it } from "vitest";

import type { Scenario } from "@/lib/api/types";

import { biggerRun, sampleOf, sizeWords } from "./sample-next";

const card = (sizes: Partial<Pick<Scenario, "servers" | "rate">>): Scenario => ({
  id: "openssh.bruteforce",
  title: "Someone keeps guessing passwords",
  technology: "OpenSSH",
  source: "security",
  source_name: "Security and sign-ins",
  summary: "",
  system: "openssh",
  benign: false,
  headline: true,
  servers: null,
  rate: null,
  ...sizes,
});

const servers = {
  question: "How many servers?",
  unit: "servers" as const,
  default: 2,
  options: [2, 6, 24].map((n) => ({ value: n, label: `${n} servers` })),
};
const rate = {
  question: "How fast do the problem lines come?",
  unit: "per_minute" as const,
  default: 12,
  options: [12, 60].map((n) => ({ value: n, label: `${n} lines a minute` })),
};

describe("sampleOf", () => {
  it("reads the sample a run was built from", () => {
    expect(sampleOf({ sample: { id: "openssh.bruteforce", servers: 6, rate: null } })).toEqual({
      id: "openssh.bruteforce",
      servers: 6,
      rate: null,
    });
  });

  it("finds none in a run started from pasted logs", () => {
    expect(sampleOf({ sample: null })).toBeNull();
    expect(sampleOf({})).toBeNull();
    expect(sampleOf(undefined)).toBeNull();
    expect(sampleOf({ sample: { servers: 6 } })).toBeNull();
  });
});

describe("biggerRun", () => {
  it("offers the next number of servers up", () => {
    const sample = { id: "openssh.bruteforce", servers: 2, rate: null };
    expect(biggerRun(card({ servers }), sample)).toEqual({
      servers: 6,
      rate: null,
      label: "Run it on 6 servers",
    });
  });

  it("offers a faster rate where the sample has no servers to choose", () => {
    const sample = { id: "hdfs.block_serve_exceptions", servers: null, rate: 12 };
    expect(biggerRun(card({ rate }), sample)?.label).toBe("Run it faster, at 60 lines a minute");
  });

  it("offers nothing at the largest size, or for a sample without sizes", () => {
    expect(biggerRun(card({ servers }), { id: "x", servers: 24, rate: null })).toBeNull();
    expect(biggerRun(card({}), { id: "x", servers: null, rate: null })).toBeNull();
    expect(biggerRun(undefined, { id: "x", servers: 2, rate: null })).toBeNull();
  });
});

describe("sizeWords", () => {
  it("names the size in the card's words", () => {
    expect(sizeWords({ id: "x", servers: 6, rate: null })).toBe("on 6 servers");
    expect(sizeWords({ id: "x", servers: 1, rate: null })).toBe("on 1 server");
    expect(sizeWords({ id: "x", servers: null, rate: 60 })).toBe("at 60 lines a minute");
    expect(sizeWords(null)).toBe("");
  });
});
