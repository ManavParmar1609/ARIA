// @vitest-environment node
// (happy-dom drops "forbidden" request headers such as cookie and origin; servers see them.)
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

const KEYS: Record<string, string> = { "k-ana": "ana" };

/** A stand-in ARIA API: /api/v1/me answers 401 unless a known key is sent (or keys are off). */
function api({ open = false } = {}) {
  return vi.fn(async (_url: URL, init: RequestInit) => {
    const key = (init.headers as Headers).get("x-api-key") ?? "";
    if (open)
      return Response.json({ name: "anonymous", authenticated: false, auth_required: false });
    const name = KEYS[key];
    if (!name) return Response.json({ detail: "missing or invalid API key" }, { status: 401 });
    return Response.json({ name, authenticated: true, auth_required: true });
  });
}

const req = (method: string, init: { cookie?: string; body?: unknown } = {}) =>
  new NextRequest("http://localhost:3000/api/session", {
    method,
    headers: { ...(init.cookie ? { cookie: init.cookie } : {}), "sec-fetch-site": "same-origin" },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });

afterEach(() => vi.unstubAllGlobals());

describe("session", () => {
  it("needs no sign-in when the API is open", async () => {
    vi.stubGlobal("fetch", api({ open: true }));
    expect(await (await GET(req("GET"))).json()).toEqual({
      authRequired: false,
      signedIn: false,
      name: null,
      reachable: true,
    });
  });

  it("signs in with a valid key and keeps it in an HttpOnly cookie", async () => {
    vi.stubGlobal("fetch", api());
    expect((await (await GET(req("GET"))).json()).authRequired).toBe(true);
    const refused = await POST(req("POST", { body: { key: "wrong" } }));
    expect(refused.status).toBe(401);
    const ok = await POST(req("POST", { body: { key: "k-ana" } }));
    expect(await ok.json()).toMatchObject({ signedIn: true, name: "ana" });
    const cookie = ok.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("aria_key=k-ana");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Strict");
    expect(cookie).toContain("Path=/api");
    const session = await (await GET(req("GET", { cookie: "aria_key=k-ana" }))).json();
    expect(session).toMatchObject({ signedIn: true, name: "ana" });
  });

  it("forgets a key the API no longer accepts, and signs out", async () => {
    vi.stubGlobal("fetch", api());
    const stale = await GET(req("GET", { cookie: "aria_key=revoked" }));
    expect(stale.headers.get("set-cookie")).toContain("Max-Age=0");
    const out = DELETE(req("DELETE"));
    expect(out.status).toBe(204);
    expect(out.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  it("reports an unreachable API instead of asking to sign in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    expect((await (await GET(req("GET"))).json()).reachable).toBe(false);
  });
});
