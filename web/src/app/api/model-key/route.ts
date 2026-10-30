import { type NextRequest } from "next/server";

import type { ModelKeyCheck, SavedModelKey } from "@/lib/api/model-key";
import {
  MODEL_KEY_COOKIE,
  MODEL_KEY_MAX_AGE_S,
  MODEL_KEY_SHAPE,
  MODEL_KIND_SHAPE,
  apiBase,
  cookieOptions,
  isSameOrigin,
  keyFrom,
  modelKeyFrom,
  problem,
  readBody,
  type ModelKey,
} from "@/lib/server/upstream";

// A visitor's own model key. Saving it asks the ARIA API to check it with the provider first, and
// only an accepted key is kept, in an HttpOnly, SameSite=Strict cookie scoped to /api that page
// scripts cannot read. Reading it back tells the page which provider and the last four
// characters, never the key.

const noStore = { "cache-control": "no-store" };

export function GET(request: NextRequest) {
  const saved = modelKeyFrom(request);
  const body: SavedModelKey = saved
    ? { provider: saved.provider, ending: saved.key.slice(-4) }
    : { provider: null, ending: null };
  return Response.json(body, { headers: noStore });
}

async function check(request: NextRequest, modelKey: ModelKey): Promise<Response> {
  const headers = new Headers({
    "x-model-provider": modelKey.provider,
    "x-model-key": modelKey.key,
  });
  const apiKey = keyFrom(request);
  if (apiKey) headers.set("x-api-key", apiKey);
  return fetch(new URL(apiBase() + "/api/v1/model-key/check"), {
    method: "POST",
    headers,
    cache: "no-store",
    redirect: "manual",
    signal: request.signal,
  });
}

export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return problem(403, "Cross-site requests are not allowed.");
  const raw = await readBody(request, 4 * 1024);
  if (raw instanceof Response) return raw;
  let provider = "";
  let key = "";
  try {
    const body = JSON.parse(new TextDecoder().decode(raw)) as { provider?: unknown; key?: unknown };
    provider = typeof body.provider === "string" ? body.provider.trim() : "";
    key = typeof body.key === "string" ? body.key.trim() : "";
  } catch {
    return problem(400, 'Send the key as JSON: {"provider": "...", "key": "..."}.');
  }
  if (!MODEL_KIND_SHAPE.test(provider)) return problem(400, "Choose the key's provider.");
  if (!MODEL_KEY_SHAPE.test(key)) {
    return problem(
      400,
      "That does not look like an API key: paste the whole key, without spaces or line breaks.",
    );
  }

  let upstream: Response;
  try {
    upstream = await check(request, { provider, key });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return problem(502, "The ARIA API is not reachable. Check that it is running.");
  }
  if (!upstream.ok) {
    const detail = ((await upstream.json().catch(() => ({}))) as { detail?: unknown }).detail;
    return problem(
      upstream.status >= 500 ? 502 : upstream.status,
      typeof detail === "string" ? detail : "The key could not be checked. Try again.",
    );
  }
  const result = (await upstream.json()) as ModelKeyCheck;
  const response = Response.json(result, { headers: noStore });
  if (result.accepted) {
    const options = cookieOptions(request);
    const parts = [
      `${MODEL_KEY_COOKIE}=${provider}~${key}`,
      `Path=${options.path}`,
      `Max-Age=${MODEL_KEY_MAX_AGE_S}`,
      "HttpOnly",
      "SameSite=Strict",
      ...(options.secure ? ["Secure"] : []),
    ];
    response.headers.append("set-cookie", parts.join("; "));
  }
  return response;
}

export function DELETE(request: NextRequest) {
  if (!isSameOrigin(request)) return problem(403, "Cross-site requests are not allowed.");
  return new Response(null, {
    status: 204,
    headers: {
      "set-cookie": `${MODEL_KEY_COOKIE}=; Path=/api; Max-Age=0; HttpOnly; SameSite=Strict`,
    },
  });
}
