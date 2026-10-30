/** Liveness for the container and load balancer: answers without calling the ARIA API. */
export function GET(): Response {
  return Response.json({ status: "ok" }, { headers: { "cache-control": "no-store" } });
}
