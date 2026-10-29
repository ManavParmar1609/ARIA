import { type NextRequest } from "next/server";

import { type Session } from "@/lib/api/session";
import {
  KEY_COOKIE,
  cookieOptions,
  forward,
  isSameOrigin,
  keyFrom,
  problem,
} from "@/lib/server/upstream";

// Signing in stores an API key in an HttpOnly, SameSite=Strict cookie scoped to /api. The key is
// checked against the API first, so a wrong key is refused here rather than on every request.

interface Me {
  name: string;
  authenticated: boolean;
  auth_required: boolean;
}

async function whoAmI(request: NextRequest, key?: string): Promise<{ status: number; me?: Me }> {
  const response = await forward(request, "/api/v1/me", { key: key ?? "", method: "GET" });
  if (!response.ok) return { status: response.status };
  return { status: response.status, me: (await response.json()) as Me };
}

export async function GET(request: NextRequest) {
  const key = keyFrom(request);
  const { status, me } = await whoAmI(request, key);
  let session: Session;
  if (me) {
    session = {
      authRequired: me.auth_required,
      signedIn: me.authenticated,
      name: me.authenticated ? me.name : null,
      reachable: true,
    };
  } else if (status === 401) {
    session = { authRequired: true, signedIn: false, name: null, reachable: true };
  } else {
    session = { authRequired: false, signedIn: false, name: null, reachable: false };
  }
  const response = Response.json(session, { headers: { "cache-control": "no-store" } });
  if (key && status === 401) {
    // The stored key no longer works (rotated or revoked): forget it.
    const cleared = new Response(response.body, response);
    cleared.headers.append(
      "set-cookie",
      `${KEY_COOKIE}=; Path=/api; Max-Age=0; HttpOnly; SameSite=Strict`,
    );
    return cleared;
  }
  return response;
}

export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return problem(403, "Cross-site requests are not allowed.");
  let key = "";
  try {
    const body = (await request.json()) as { key?: unknown };
    key = typeof body.key === "string" ? body.key.trim() : "";
  } catch {
    return problem(400, 'Send the API key as JSON: {"key": "..."}.');
  }
  if (!key || key.length > 512) return problem(400, "Enter an API key.");
  const { status, me } = await whoAmI(request, key);
  if (status === 401) return problem(401, "That key was not accepted. Check it and try again.");
  if (!me) return problem(502, "The ARIA API is not reachable. Check that it is running.");
  if (!me.auth_required) {
    return Response.json({ authRequired: false, signedIn: false, name: null, reachable: true });
  }
  const response = Response.json({
    authRequired: true,
    signedIn: true,
    name: me.name,
    reachable: true,
  } satisfies Session);
  const options = cookieOptions(request);
  const parts = [
    `${KEY_COOKIE}=${encodeURIComponent(key)}`,
    `Path=${options.path}`,
    `Max-Age=${options.maxAge}`,
    "HttpOnly",
    "SameSite=Strict",
    ...(options.secure ? ["Secure"] : []),
  ];
  response.headers.append("set-cookie", parts.join("; "));
  response.headers.set("cache-control", "no-store");
  return response;
}

export function DELETE(request: NextRequest) {
  if (!isSameOrigin(request)) return problem(403, "Cross-site requests are not allowed.");
  return new Response(null, {
    status: 204,
    headers: { "set-cookie": `${KEY_COOKIE}=; Path=/api; Max-Age=0; HttpOnly; SameSite=Strict` },
  });
}
