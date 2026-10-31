// A browser's private session id, as a cookie. The request proxy (src/proxy.ts) gives one to a
// browser that has none, with the first console page it opens; the API routes read it
// (lib/server/upstream.ts). Both make and read it here, so they always agree.

export const VISITOR_COOKIE = "aria_visitor";
export const VISITOR_SHAPE = /^[A-Za-z0-9_-]{16,64}$/;
const VISITOR_MAX_AGE_S = 30 * 24 * 60 * 60;

/** The Set-Cookie value for a visitor id. It goes with the console's pages as well as its API
 * routes, so the proxy sees it on every page load and never hands out a second id; scripts
 * never see it (HttpOnly). */
export function visitorCookieValue(id: string, secure: boolean): string {
  return [
    `${VISITOR_COOKIE}=${id}`,
    "Path=/",
    `Max-Age=${VISITOR_MAX_AGE_S}`,
    "HttpOnly",
    "SameSite=Strict",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}

/** Clears the id earlier versions kept for /api alone, so a browser holds one id, not two. */
export function staleVisitorCookie(secure: boolean): string {
  return [
    `${VISITOR_COOKIE}=`,
    "Path=/api",
    "Max-Age=0",
    "HttpOnly",
    "SameSite=Strict",
    ...(secure ? ["Secure"] : []),
  ].join("; ");
}
