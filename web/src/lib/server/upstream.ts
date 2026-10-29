import "server-only";

import { type NextRequest } from "next/server";

/** Where the ARIA API listens, as seen from this server (never from the browser). */
export function apiBase(): string {
  return (process.env.ARIA_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

/** The HttpOnly cookie that holds the signed-in API key. Page scripts cannot read it. */
export const KEY_COOKIE = "aria_key";
const KEY_MAX_AGE_S = 12 * 60 * 60;

const FORWARD_REQUEST_HEADERS = ["accept", "content-type", "last-event-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "retry-after", "cache-control", "x-request-id"];
const MAX_BODY_BYTES = 8 * 1024 * 1024;

export function keyFrom(request: NextRequest): string | undefined {
  const value = request.cookies.get(KEY_COOKIE)?.value;
  return value ? value : undefined;
}

export function cookieOptions(request: NextRequest) {
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ??
    request.nextUrl.protocol.replace(":", "");
  return {
    httpOnly: true,
    sameSite: "strict" as const,
    secure: proto === "https",
    path: "/api",
    maxAge: KEY_MAX_AGE_S,
  };
}

/**
 * Writes must come from this site's own pages. The key cookie is SameSite=Strict already; this
 * also refuses cross-site form posts and requests from other origins that carry no cookie.
 */
export function isSameOrigin(request: NextRequest): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return false;
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host === (request.headers.get("host") ?? request.nextUrl.host);
  } catch {
    return false;
  }
}

export function problem(status: number, detail: string): Response {
  return Response.json({ detail }, { status, headers: { "cache-control": "no-store" } });
}

/**
 * Forward a request to the ARIA API with the signed-in key, streaming the answer back
 * (server-sent events included). Only known-safe headers cross in either direction.
 */
export async function forward(
  request: NextRequest,
  path: string,
  init: { key?: string; method?: string } = {},
): Promise<Response> {
  const method = init.method ?? request.method;
  if (method !== "GET" && method !== "HEAD" && !isSameOrigin(request)) {
    return problem(403, "Cross-site requests are not allowed.");
  }
  const target = new URL(apiBase() + path);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const key = init.key ?? keyFrom(request);
  if (key) headers.set("x-api-key", key);

  let body: string | undefined;
  if (method !== "GET" && method !== "HEAD") {
    body = await request.text();
    if (body.length > MAX_BODY_BYTES) return problem(413, "The request is larger than 8 MB.");
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    console.error("ARIA API unreachable", { target: target.origin, error: String(error) });
    return problem(502, "The ARIA API is not reachable. Check that it is running.");
  }

  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  if (out.get("content-type")?.startsWith("text/event-stream")) {
    // no-transform keeps the compression layer from buffering the stream.
    out.set("cache-control", "no-cache, no-transform");
    out.set("x-accel-buffering", "no");
  } else if (!out.has("cache-control")) {
    out.set("cache-control", "no-store");
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
