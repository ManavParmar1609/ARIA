// Copy the measured results the site quotes into src/data, so the web build (and its Docker
// image) does not reach outside web/. CI runs this and fails if a copy differs from docs/.
//
//   docs/eval-results.json  offline evaluation, all suites (make eval)
//   docs/eval-live.json     end-to-end runs through a live LLM provider
//   llms.txt                served by the site at /llms.txt (copied as src/data/llms.json)
//
// src/data/demo-run.json is written by scripts/record_demo_run.py instead.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const docs = resolve(here, "../../docs");
const out = resolve(here, "../src/data");
mkdirSync(out, { recursive: true });
for (const name of ["eval-results.json", "eval-live.json"]) {
  copyFileSync(resolve(docs, name), resolve(out, name));
  console.log(`synced src/data/${name}`);
}
const llms = readFileSync(resolve(here, "../../llms.txt"), "utf8");
writeFileSync(resolve(out, "llms.json"), `${JSON.stringify({ text: llms }, null, 2)}\n`);
console.log("synced src/data/llms.json");
