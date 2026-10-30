// @vitest-environment node
// (happy-dom drops "forbidden" request headers such as cookie and origin; servers see them.)
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

const KEY = "sk-ant-visitor-0123456789abcdefghij";

/** A stand-in ARIA API whose key check accepts only KEY. */
function api(status = 200) {
  return vi.fn(async (_url: URL, init: RequestInit) => {
    const headers = init.headers as Headers;
    if (status !== 200)
      return Response.json({ detail: "This server does not take keys." }, { status });
    const accepted = headers.get("x-model-key") === KEY;
    return Response.json({
      provider: headers.get("x-model-provider"),
      accepted,
      model: "claude-opus-5-5",
      detail: accepted ? "Anthropic accepted the key." : "Anthropic did not accept this key.",
    });
  });
}

const req = (method: string, init: { cookie?: string; body?: unknown; site?: string } = {}) =>
  new NextRequest("http://localhost:3000/api/model-key", {
    method,
    headers: {
      ...(init.cookie ? { cookie: init.cookie } : {}),
      "sec-fetch-site": init.site ?? "same-origin",
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });

afterEach(() => vi.unstubAllGlobals());

describe("model key", () => {
  it("keeps an accepted key in an HttpOnly cookie and shows only its provider and ending", async () => {
    vi.stubGlobal("fetch", api());
    const saved = await POST(req("POST", { body: { provider: "claude", key: KEY } }));
    expect(await saved.json()).toMatchObject({ accepted: true, provider: "claude" });
    const cookie = saved.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`aria_model_key=claude~${KEY}`);
    for (const flag of ["HttpOnly", "SameSite=Strict", "Path=/api", "Max-Age=28800"]) {
      expect(cookie).toContain(flag);
    }
    const shown = await (await GET(req("GET", { cookie: `aria_model_key=claude~${KEY}` }))).json();
    expect(shown).toEqual({ provider: "claude", ending: KEY.slice(-4) });
    expect(JSON.stringify(shown)).not.toContain(KEY.slice(0, 12));
  });

  it("keeps nothing the provider refused, and says why", async () => {
    vi.stubGlobal("fetch", api());
    const refused = await POST(
      req("POST", { body: { provider: "claude", key: "sk-ant-wrong-0123456789abcdef" } }),
    );
    expect(await refused.json()).toMatchObject({ accepted: false });
    expect(refused.headers.get("set-cookie")).toBeNull();
  });

  it("checks the shape before asking anyone, and refuses other sites", async () => {
    const fetch = api();
    vi.stubGlobal("fetch", fetch);
    for (const body of [
      { provider: "claude", key: "short" },
      { provider: "claude", key: `${KEY}\r\nx: 1` },
      { provider: "", key: KEY },
      { provider: "Claude!", key: KEY },
    ]) {
      expect((await POST(req("POST", { body }))).status).toBe(400);
    }
    const cross = await POST(
      req("POST", { body: { provider: "claude", key: KEY }, site: "cross-site" }),
    );
    expect(cross.status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes on the API's reason when it takes no keys, and forgets a key", async () => {
    vi.stubGlobal("fetch", api(422));
    const off = await POST(req("POST", { body: { provider: "claude", key: KEY } }));
    expect(off.status).toBe(422);
    expect((await off.json()).detail).toContain("does not take keys");
    const forgot = DELETE(req("DELETE"));
    expect(forgot.status).toBe(204);
    expect(forgot.headers.get("set-cookie")).toContain("aria_model_key=; Path=/api; Max-Age=0");
    expect(DELETE(req("DELETE", { site: "cross-site" })).status).toBe(403);
    expect(await (await GET(req("GET"))).json()).toEqual({ provider: null, ending: null });
  });
});
