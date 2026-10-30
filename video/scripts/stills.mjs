// Render one still from the end of each scene (bundling once) to review the layout:
//   node scripts/stills.mjs            -> out/stills/<scene>.png
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || null;
// Frames just before each scene fades out (scene starts follow AriaDemo.tsx's lengths).
const FRAMES = {
  opening: 120,
  intake: 380,
  parse: 640,
  severity: 1040,
  investigate: 1360,
  report: 1730,
  review: 1960,
  measured: 2330,
  close: 2500,
};
const only = process.argv.slice(2);
const serveUrl = await bundle({ entryPoint: resolve(here, "../src/index.ts") });
const composition = await selectComposition({ serveUrl, id: "AriaDemo", browserExecutable });
mkdirSync(resolve(here, "../out/stills"), { recursive: true });
for (const [name, frame] of Object.entries(FRAMES)) {
  if (only.length && !only.includes(name)) continue;
  const output = resolve(here, `../out/stills/${name}.png`);
  await renderStill({ composition, serveUrl, frame, output, browserExecutable });
  console.log(`${name}: frame ${frame} -> ${output}`);
}
