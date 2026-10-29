import { type NextRequest } from "next/server";

import { forward, problem } from "@/lib/server/upstream";

// /api/v1/* on this server is the ARIA API's /api/v1/*, called with the signed-in key.

function upstreamPath(segments: string[]): string | null {
  if (segments.some((s) => s === "" || s === "." || s === ".." || /[\\/]/.test(s))) return null;
  return "/api/v1/" + segments.map(encodeURIComponent).join("/");
}

async function handle(request: NextRequest, ctx: RouteContext<"/api/v1/[...path]">) {
  const { path } = await ctx.params;
  const target = upstreamPath(path);
  if (target === null) return problem(400, "Invalid API path.");
  return forward(request, target);
}

export { handle as GET, handle as POST, handle as DELETE };
