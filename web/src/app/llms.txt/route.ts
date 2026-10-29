import llms from "@/data/llms.json";

// The repository's llms.txt (copied by `pnpm sync:data`), so agents find the docs from the site.

export const dynamic = "force-static";

export function GET() {
  return new Response(llms.text, {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
