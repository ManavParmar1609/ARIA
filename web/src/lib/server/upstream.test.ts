// @vitest-environment node
// (happy-dom drops "forbidden" request headers such as cookie and origin; servers see them.)
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  carriesModelKey,
  cookieOptions,
  forward,
  isSameOrigin,
  modelKeyFrom,
  readBody,
  upstreamPath,
} from "./upstream";

const req = (
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: string } = {},
) => new NextRequest(`http://localhost:3000${path}`, init);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("upstreamPath", () => {
  it("maps segments onto the API's /api/v1 and refuses traversal", () => {
    expect(upstreamPath(["runs", "run-1", "report"])).toBe("/api/v1/runs/run-1/report");
    expect(upstreamPath(["runbooks", "a b"])).toBe("/api/v1/runbooks/a%20b");
    for (const bad of [[], [".."], ["runs", "."], ["runs", ""], ["a\\b"], ["a/b"]]) {
      expect(upstreamPath(bad)).toBeNull();
    }
  });
});

describe("isSameOrigin", () => {
  it("accepts this site's own requests and refuses others", () => {
    expect(isSameOrigin(req("/x", { headers: { "sec-fetch-site": "same-origin" } }))).toBe(true);
    expect(isSameOrigin(req("/x"))).toBe(true);
    expect(isSameOrigin(req("/x", { headers: { "sec-fetch-site": "cross-site" } }))).toBe(false);
    expect(
      isSameOrigin(
        req("/x", { headers: { origin: "https://evil.example", host: "localhost:3000" } }),
      ),
    ).toBe(false);
    expect(
      isSameOrigin(
        req("/x", { headers: { origin: "http://localhost:3000", host: "localhost:3000" } }),
      ),
    ).toBe(true);
  });
});

describe("cookieOptions", () => {
  it("marks the key cookie Secure only over https", () => {
    expect(cookieOptions(req("/x")).secure).toBe(false);
    expect(cookieOptions(req("/x", { headers: { "x-forwarded-proto": "https" } }))).toMatchObject({
      secure: true,
      httpOnly: true,
      sameSite: "strict",
      path: "/api",
    });
  });
});

describe("forward", () => {
  it("adds the signed-in key and forwards only safe headers", async () => {
    vi.stubEnv("ARIA_API_URL", "http://api.internal:8000/");
    const fetch = vi.fn(
      async () =>
        new Response('{"ok":true}', {
          headers: { "content-type": "application/json", "set-cookie": "x=1" },
        }),
    );
    vi.stubGlobal("fetch", fetch);
    const response = await forward(
      req("/api/v1/runs?limit=5", {
        headers: {
          cookie: "aria_key=k-ana",
          accept: "application/json",
          "x-forwarded-for": "1.2.3.4",
          authorization: "Bearer stolen",
        },
      }),
      "/api/v1/runs",
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toBeNull();
    const [url, init] = fetch.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe("http://api.internal:8000/api/v1/runs?limit=5");
    const headers = init.headers as Headers;
    expect(headers.get("x-api-key")).toBe("k-ana");
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
  });

  it("passes server-sent events through without buffering", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("data: {}\n\n", { headers: { "content-type": "text/event-stream" } }),
      ),
    );
    const response = await forward(req("/api/v1/runs/r/stream"), "/api/v1/runs/r/stream");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
  });

  it("refuses cross-site writes and explains an unreachable API", async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    vi.stubGlobal("fetch", fetch);
    const crossSite = await forward(
      req("/api/v1/runs", {
        method: "POST",
        body: "{}",
        headers: { "sec-fetch-site": "cross-site" },
      }),
      "/api/v1/runs",
    );
    expect(crossSite.status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
    const down = await forward(req("/api/v1/runs"), "/api/v1/runs");
    expect(down.status).toBe(502);
    expect(await down.json()).toEqual({
      detail: "The ARIA API is not reachable. Check that it is running.",
    });
  });
});

describe("a visitor's own model key", () => {
  const KEY = "AIzaVisitorKey-0123456789abcdefghijklmno";
  const cookie = `aria_model_key=gemini~${KEY}`;

  it("goes only with requests that can call a model", () => {
    for (const path of [
      "/api/v1/runs",
      "/api/v1/runs/run-1/fork",
      "/api/v1/real-incidents/hdfs-1/replay",
      "/api/v1/ask",
      "/agui",
    ]) {
      expect(carriesModelKey("POST", path)).toBe(true);
    }
    for (const [method, path] of [
      ["GET", "/api/v1/runs"],
      ["POST", "/api/v1/runs/run-1/review"],
      ["DELETE", "/api/v1/runs/run-1"],
      ["POST", "/api/v1/alerts"],
      ["POST", "/api/v1/runs/run-1/fork/x"],
    ] as const) {
      expect(carriesModelKey(method, path)).toBe(false);
    }
  });

  it("reads only a well-formed cookie", () => {
    expect(modelKeyFrom(req("/x", { headers: { cookie } }))).toEqual({
      provider: "gemini",
      key: KEY,
    });
    for (const bad of ["gemini", `~${KEY}`, "gemini~short", `Gemini~${KEY}`, `gemini~${KEY} x`]) {
      expect(modelKeyFrom(req("/x", { headers: { cookie: `aria_model_key=${bad}` } }))).toBe(
        undefined,
      );
    }
  });

  it("is forwarded with a new run and never with anything else", async () => {
    const fetch = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetch);
    const sent = (call: number) => (fetch.mock.calls[call] as unknown as [URL, RequestInit])[1];
    await forward(
      req("/api/v1/runs", { method: "POST", headers: { cookie }, body: "{}" }),
      "/api/v1/runs",
    );
    expect((sent(0).headers as Headers).get("x-model-key")).toBe(KEY);
    expect((sent(0).headers as Headers).get("x-model-provider")).toBe("gemini");
    await forward(req("/api/v1/runs", { headers: { cookie } }), "/api/v1/runs");
    await forward(
      req("/api/v1/runs/r/review", { method: "POST", headers: { cookie }, body: "{}" }),
      "/api/v1/runs/r/review",
    );
    for (const call of [1, 2]) {
      expect((sent(call).headers as Headers).get("x-model-key")).toBeNull();
    }
  });
});

describe("readBody", () => {
  const streamed = (chunks: number, size: number) =>
    new NextRequest("http://localhost:3000/api/v1/runs", {
      method: "POST",
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          for (let i = 0; i < chunks; i++) controller.enqueue(new Uint8Array(size));
          controller.close();
        },
      }),
      duplex: "half", // Node needs this for a streamed request body
    });

  it("returns the bytes of a body within the limit", async () => {
    const body = await readBody(req("/x", { method: "POST", body: "héllo" }));
    expect(body).toBeInstanceOf(Uint8Array);
    expect(new TextDecoder().decode(body as Uint8Array)).toBe("héllo");
  });

  it("refuses a declared length over the limit before reading anything", async () => {
    const response = await readBody(
      req("/x", { method: "POST", body: "{}", headers: { "content-length": "999999999" } }),
    );
    expect((response as Response).status).toBe(413);
  });

  it("stops reading a body that grows past the limit", async () => {
    const response = await readBody(streamed(5, 1024), 4 * 1024);
    expect((response as Response).status).toBe(413);
    expect(await (response as Response).json()).toEqual({
      detail: "The request is larger than 4 KB.",
    });
  });
});
