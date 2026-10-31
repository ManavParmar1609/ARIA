import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

function answer(response: Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response),
  );
}

describe("API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says what to do about a bare server error", async () => {
    answer(new Response("Internal Server Error", { status: 500 }));
    await expect(apiFetch("/api/v1/runs")).rejects.toMatchObject({
      status: 500,
      detail: expect.stringMatching(/unexpected error.*Try again/),
    });
  });

  it("does not repeat the stock reason phrase as the explanation", async () => {
    answer(Response.json({ detail: "Internal Server Error" }, { status: 500 }));
    await expect(apiFetch("/api/v1/runs")).rejects.toMatchObject({
      detail: expect.not.stringContaining("Internal Server Error"),
    });
  });

  it("says how large a paste may be, in megabytes, when a server refuses it", async () => {
    answer(Response.json({ detail: "request body larger than 4194304 bytes" }, { status: 413 }));
    await expect(apiFetch("/api/v1/runs", { method: "POST", body: "{}" })).rejects.toMatchObject({
      status: 413,
      detail: expect.stringMatching(/larger than this server accepts per triage \(4 MB\)/),
    });
    answer(Response.json({ detail: "The request is larger than 8 MB." }, { status: 413 }));
    await expect(apiFetch("/api/v1/runs", { method: "POST", body: "{}" })).rejects.toMatchObject({
      detail: expect.stringContaining("(8 MB)"),
    });
  });

  it("keeps an explanation the API wrote", async () => {
    answer(Response.json({ detail: "Run run-1 not found" }, { status: 404 }));
    await expect(apiFetch("/api/v1/runs/run-1")).rejects.toMatchObject({
      status: 404,
      detail: "Run run-1 not found",
    });
  });
});
