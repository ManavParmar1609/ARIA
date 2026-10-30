# 0010. A backend-for-frontend keeps the API key away from page scripts

## Status

Accepted.

## Context

The web console calls the API for a signed-in person. If page JavaScript held the API key, any
script on the page (an injected one, or a compromised dependency) could read it and send it
elsewhere, and the API would need CORS for the console's origin. The API also streams server-sent
events, which a proxy must not buffer.

## Decision

The Next.js server is the only part of the web app that talks to the API
([`upstream.ts`](../../web/src/lib/server/upstream.ts)):

- **Browser code calls its own origin.** Every request goes to this server's `/api/*` routes
  ([`client.ts`](../../web/src/lib/api/client.ts)). `/api/v1/[...path]` forwards to the API's
  `/api/v1/*`, and `/api/agui` and `/api/ready` forward to `/agui` and `/readyz`. The API's
  address, `ARIA_API_URL`, is a server-side setting the browser never sees.
- **Sign-in puts the key in a cookie no script can read.** The person types the key into the
  sign-in form once. `POST /api/session` checks it against the API's `/api/v1/me`, then stores it
  in an `HttpOnly`, `SameSite=Strict` cookie scoped to `/api`, `Secure` over HTTPS, for 12 hours
  ([`session/route.ts`](../../web/src/app/api/session/route.ts)). A key the API stops accepting
  is cleared at the next session check. Nothing goes into browser storage.
- **The proxy adds the key and filters everything else.** It sends the key as `x-api-key` and
  forwards an allowlist of headers each way: `accept`, `content-type` and `last-event-id` in;
  `content-type`, `retry-after`, `cache-control` and `x-request-id` out. It refuses path segments
  that could escape `/api/v1` and bodies over 8 MB, and does not follow redirects.
- **Writes must come from this site.** Requests other than GET and HEAD are refused unless
  `Sec-Fetch-Site` and `Origin` say they come from the console's own pages, on top of the
  `SameSite=Strict` cookie.
- **Streams pass straight through.** Event streams get `cache-control: no-cache, no-transform` and
  `x-accel-buffering: no`, so nothing buffers SSE.

## Alternatives considered

- **Call the API from the browser with the key in memory or storage.** Every script could read
  the key, and the API would need CORS.
- **One service key held by the web server.** Everyone would act as the same identity. ARIA
  records the signed-in key's name as the reviewer of each decision, so each person signs in with
  their own key.

## Consequences

- After sign-in no page script can read the key, and the API needs no CORS entry for the console.
- The web server holds no secrets of its own (its Azure container app has no key settings), so
  it can be replaced or scaled freely.
- Every console request takes one extra hop through the web server.
- An XSS flaw in the console could still make same-origin requests while someone is signed in.
  It could not take the key away.
