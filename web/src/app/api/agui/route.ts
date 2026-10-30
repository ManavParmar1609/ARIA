import { type NextRequest } from "next/server";

import { forward } from "@/lib/server/upstream";

// The ARIA API's AG-UI agent endpoint, for the console's chat triage (and any AG-UI client
// running in the browser). The answer is an AG-UI event stream.
export function POST(request: NextRequest) {
  return forward(request, "/agui");
}
