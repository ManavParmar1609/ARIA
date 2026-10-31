// Browser-side access to the ARIA API. Every request goes to this web server's own /api routes,
// which forward it to the API with the signed-in key (see src/app/api/v1/[...path]/route.ts), so
// no key ever reaches page JavaScript.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  get needsSignIn(): boolean {
    return this.status === 401;
  }
}

// The stock reason phrases servers send with a 5xx: they say nothing a person can act on.
const STOCK = new Set(["Internal Server Error", "Bad Gateway", "Service Unavailable"]);

/** A refused paste, in sizes a person can act on. The API says "request body larger than N
 * bytes"; this console's own server says "The request is larger than 8 MB." */
function tooLarge(body: unknown): string {
  const detail = body && typeof body === "object" && "detail" in body ? String(body.detail) : "";
  const bytes = /larger than (\d+) bytes/.exec(detail)?.[1];
  const most = bytes
    ? `${Math.round((Number(bytes) / 1024 / 1024) * 10) / 10} MB`
    : (/larger than ([\d.]+ ?[KMG]B)/.exec(detail)?.[1] ?? null);
  return most
    ? `These logs are larger than this server accepts per triage (${most}). Send fewer lines, or split them over several triages.`
    : "These logs are larger than this server accepts per triage. Send fewer lines, or split them over several triages.";
}

function describe(status: number, body: unknown): string {
  // A busy server's own words ("rate limit exceeded") say nothing a visitor can act on.
  if (status === 429) return "ARIA is busy right now. Wait a moment and try again.";
  if (status === 413) return tooLarge(body);
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && !STOCK.has(detail)) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown; loc?: unknown };
      const where = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      if (typeof first.msg === "string") return where ? `${where}: ${first.msg}` : first.msg;
    }
  }
  if (status === 401) return "Sign in with an API key to use the console.";
  if (status === 502 || status === 503 || status === 504) {
    return "The ARIA API is not reachable. Check that it is running.";
  }
  if (status >= 500) {
    return "The ARIA API hit an unexpected error. Try again; if it keeps failing, its log says why.";
  }
  return `The request failed (HTTP ${status}).`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        accept: "application/json",
        ...(init?.body ? { "content-type": "application/json" } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "The console cannot reach its server. Check your connection.");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) throw new ApiError(response.status, describe(response.status, body));
  return body as T;
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) });
}
