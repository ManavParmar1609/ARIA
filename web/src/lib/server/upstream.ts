import "server-only";

import { type NextRequest } from "next/server";

import { MAX_BODY_BYTES } from "@/lib/limits";

/** Where the ARIA API listens, as seen from this server (never from the browser). */
export function apiBase(): string {
  return (process.env.ARIA_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

/** The HttpOnly cookie that holds the signed-in API key. Page scripts cannot read it. */
export const KEY_COOKIE = "aria_key";
const KEY_MAX_AGE_S = 12 * 60 * 60;

/**
 * The HttpOnly cookie that holds a visitor's own model key, as "<provider>~<key>". It goes to the
 * ARIA API only with the requests that can call a model, and lasts a working day at most.
 */
export const MODEL_KEY_COOKIE = "aria_model_key";
export const MODEL_KEY_MAX_AGE_S = 8 * 60 * 60;
/** A key as the API accepts it: a plain token, so it can never break a header. */
export const MODEL_KEY_SHAPE = /^[A-Za-z0-9._-]{20,200}$/;
export const MODEL_KIND_SHAPE = /^[a-z][a-z0-9-]{0,23}$/;

export interface ModelKey {
  provider: string;
  key: string;
}

/**
 * The HttpOnly cookie that holds this browser's private session id. A server that keeps visitors
 * apart (ARIA_VISITOR_SCOPE) files each visitor's incidents under it, so no one else sees them.
 * It is a random id, not a secret about the visitor, and lasts a month.
 */
export const VISITOR_COOKIE = "aria_visitor";
const VISITOR_MAX_AGE_S = 30 * 24 * 60 * 60;
const VISITOR_SHAPE = /^[A-Za-z0-9_-]{16,64}$/;

export interface Visitor {
  id: string;
  /** Made for this request, so the response must set the cookie. */
  fresh: boolean;
}

/** This browser's session id, or a new one when it has none or a malformed one. */
export function visitorFrom(request: NextRequest): Visitor {
  const value = request.cookies.get(VISITOR_COOKIE)?.value ?? "";
  if (VISITOR_SHAPE.test(value)) return { id: value, fresh: false };
  return { id: crypto.randomUUID(), fresh: true };
}

export function visitorCookie(request: NextRequest, id: string): string {
  return [
    `${VISITOR_COOKIE}=${id}`,
    "Path=/api",
    `Max-Age=${VISITOR_MAX_AGE_S}`,
    "HttpOnly",
    "SameSite=Strict",
    ...(cookieOptions(request).secure ? ["Secure"] : []),
  ].join("; ");
}

/** Requests that can call a model; only these carry a visitor's own key. */
const MODEL_KEY_ROUTES = [
  /^\/api\/v1\/runs$/,
  /^\/api\/v1\/runs\/[^/]+\/fork$/,
  /^\/api\/v1\/real-incidents\/[^/]+\/replay$/,
  /^\/api\/v1\/ask$/,
  /^\/agui$/,
];

export function carriesModelKey(method: string, path: string): boolean {
  return method === "POST" && MODEL_KEY_ROUTES.some((route) => route.test(path));
}

export function modelKeyFrom(request: NextRequest): ModelKey | undefined {
  const value = request.cookies.get(MODEL_KEY_COOKIE)?.value ?? "";
  const at = value.indexOf("~");
  const provider = value.slice(0, at);
  const key = value.slice(at + 1);
  if (at < 1 || !MODEL_KIND_SHAPE.test(provider) || !MODEL_KEY_SHAPE.test(key)) return undefined;
  return { provider, key };
}

const FORWARD_REQUEST_HEADERS = ["accept", "content-type", "last-event-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "retry-after", "cache-control", "x-request-id"];

/** The ARIA API path for this server's /api/v1/<segments>, or null if a segment is unsafe. */
export function upstreamPath(segments: string[]): string | null {
  if (segments.length === 0) return null;
  if (segments.some((s) => s === "" || s === "." || s === ".." || /[\\/]/.test(s))) return null;
  return "/api/v1/" + segments.map(encodeURIComponent).join("/");
}

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
 * The request body, or a 413 once it passes `limit` bytes. A declared length over the limit is
 * refused before anything is read, and the bytes are counted as they arrive, so an oversized
 * body never sits in memory whole.
 */
export async function readBody(
  request: NextRequest,
  limit = MAX_BODY_BYTES,
): Promise<Uint8Array<ArrayBuffer> | Response> {
  const largest = limit >= 1024 * 1024 ? `${limit / 1024 / 1024} MB` : `${limit / 1024} KB`;
  const tooLarge = () => problem(413, `The request is larger than ${largest}.`);
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > limit) return tooLarge();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const reader = request.body?.getReader();
  for (let part = await reader?.read(); part && !part.done; part = await reader?.read()) {
    size += part.value.byteLength;
    if (size > limit) {
      await reader?.cancel();
      return tooLarge();
    }
    chunks.push(part.value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

/**
 * Forward a request to the ARIA API with the signed-in key and this browser's session id,
 * streaming the answer back (server-sent events included). Only known-safe headers cross in
 * either direction. A browser without a session id gets one with the answer.
 */
export async function forward(
  request: NextRequest,
  path: string,
  init: { key?: string; method?: string; visitor?: Visitor } = {},
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
  const visitor = init.visitor ?? visitorFrom(request);
  headers.set("x-visitor-id", visitor.id);
  const modelKey = carriesModelKey(method, path) ? modelKeyFrom(request) : undefined;
  if (modelKey) {
    headers.set("x-model-provider", modelKey.provider);
    headers.set("x-model-key", modelKey.key);
  }

  let body: Uint8Array<ArrayBuffer> | undefined;
  if (method !== "GET" && method !== "HEAD") {
    const read = await readBody(request);
    if (read instanceof Response) return read;
    body = read;
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
  if (visitor.fresh) out.append("set-cookie", visitorCookie(request, visitor.id));
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
