import { NextResponse, type NextRequest } from "next/server";

import {
  VISITOR_COOKIE,
  VISITOR_SHAPE,
  staleVisitorCookie,
  visitorCookieValue,
} from "@/lib/visitor-cookie";

/**
 * Give a browser its private session id with the first console page it opens, before that page's
 * own requests go out. Those requests leave together; without the cookie, each would be given a
 * different id, the answer that came last would win, and an incident started in between would be
 * filed under an id the browser no longer holds.
 */
export function proxy(request: NextRequest) {
  if (VISITOR_SHAPE.test(request.cookies.get(VISITOR_COOKIE)?.value ?? "")) {
    return NextResponse.next();
  }
  const id = crypto.randomUUID();
  // The API routes read the id from the request, so this request already carries it.
  request.cookies.set(VISITOR_COOKIE, id);
  const response = NextResponse.next({ request: { headers: request.headers } });
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ??
    request.nextUrl.protocol.replace(":", "");
  const secure = proto === "https";
  response.headers.append("set-cookie", visitorCookieValue(id, secure));
  response.headers.append("set-cookie", staleVisitorCookie(secure));
  return response;
}

export const config = {
  // Console pages (first visits land here) and the console's own API routes; not static files.
  matcher: ["/console/:path*", "/api/:path*"],
};
