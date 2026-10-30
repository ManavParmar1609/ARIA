import { type NextRequest } from "next/server";

import { forward } from "@/lib/server/upstream";

// The API's readiness (database, LLM providers, memory size) for the console's status line.
export function GET(request: NextRequest) {
  return forward(request, "/readyz");
}
