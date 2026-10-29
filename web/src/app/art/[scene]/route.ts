import { createElement, type ComponentType } from "react";

import {
  ApproveScene,
  EvidenceScene,
  HillsBand,
  NoiseScene,
  StampScene,
} from "@/components/illustrations/scenes";
import { renderSvg } from "@/lib/svg-string";

// The landing page's decorative scenes as static .svg files, drawn from the same components at
// build time. As images they stay out of the page's HTML and out of hydration, and load lazily.
const SCENES: Record<string, ComponentType> = {
  noise: NoiseScene,
  stamp: StampScene,
  evidence: EvidenceScene,
  approve: ApproveScene,
  hills: HillsBand,
};

export const dynamic = "force-static";

export function generateStaticParams() {
  return Object.keys(SCENES).map((name) => ({ scene: `${name}.svg` }));
}

export async function GET(_request: Request, { params }: { params: Promise<{ scene: string }> }) {
  const { scene } = await params;
  const Scene = SCENES[scene.replace(/\.svg$/, "")];
  if (!Scene) return new Response("Not found", { status: 404 });
  const svg = renderSvg(createElement(Scene)).replace(
    /^<svg /,
    '<svg xmlns="http://www.w3.org/2000/svg" ',
  );
  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
