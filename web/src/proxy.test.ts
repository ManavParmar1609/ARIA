// @vitest-environment node
// (A browser-like test environment drops the Cookie header, as browsers do.)
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "./proxy";

describe("the request proxy", () => {
  it("gives a browser without a session id one, on the request and in its cookie", () => {
    const response = proxy(new NextRequest("http://localhost/console/runs/new"));
    const cookie = response.headers.get("set-cookie") ?? "";
    const id = /^aria_visitor=([0-9a-f-]{36}); Path=\/;/.exec(cookie)?.[1];
    expect(id).toBeDefined();
    expect(cookie).toContain("HttpOnly; SameSite=Strict");
    // The page's own request already carries it, so the API routes make no second id.
    expect(response.headers.get("x-middleware-request-cookie")).toContain(`aria_visitor=${id}`);
  });

  it("sends the id with every console page, so the next page load keeps it", () => {
    const first = proxy(new NextRequest("http://localhost/console/runs"));
    const [cookie, stale] = first.headers.getSetCookie();
    const id = /^aria_visitor=([^;]+)/.exec(cookie ?? "")?.[1] ?? "";
    // The id an earlier version kept for /api alone is cleared, so a browser holds just one.
    expect(stale).toBe("aria_visitor=; Path=/api; Max-Age=0; HttpOnly; SameSite=Strict");
    const next = new NextRequest("http://localhost/console/runs/run-1", {
      headers: { cookie: `aria_visitor=${id}` },
    });
    expect(proxy(next).headers.get("set-cookie")).toBeNull();
  });

  it("leaves a browser that has one as it is", () => {
    const request = new NextRequest("http://localhost/api/v1/runs", {
      headers: { cookie: "aria_visitor=0123456789abcdef0123" },
    });
    expect(proxy(request).headers.get("set-cookie")).toBeNull();
  });

  it("marks the cookie secure behind HTTPS", () => {
    const request = new NextRequest("http://localhost/console", {
      headers: { "x-forwarded-proto": "https" },
    });
    for (const cookie of proxy(request).headers.getSetCookie()) expect(cookie).toMatch(/; Secure$/);
  });
});
