// @vitest-environment node
// (happy-dom drops "forbidden" request headers such as cookie and origin; servers see them.)
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cookieOptions, forward, isSameOrigin, upstreamPath } from "./upstream";

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
