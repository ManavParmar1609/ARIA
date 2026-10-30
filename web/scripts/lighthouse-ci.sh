#!/usr/bin/env bash
# The Lighthouse gate against a production build, as CI runs it: start an offline, seeded ARIA API
# and the built web app, triage and publish one run for the run view, then run lighthouse.mjs.
#
#   pnpm build && ./scripts/lighthouse-ci.sh
#
# Needs uv (for the API) and a Chromium (Playwright's, or CHROME_PATH). Provider keys are blanked,
# so no model is ever called.
set -euo pipefail

web=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$web/.." && pwd)
api_port=${API_PORT:-8150}
web_port=${WEB_PORT:-3250}
api="http://127.0.0.1:${api_port}"
site="http://127.0.0.1:${web_port}"
data=$(mktemp -d)
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}127.0.0.1,localhost" # never send local calls to a proxy

groups=()
cleanup() {
  for group in "${groups[@]}"; do kill -- "-${group}" 2>/dev/null || true; done
  rm -rf "${data}"
}
trap cleanup EXIT

wait_for() {
  for _ in $(seq 1 120); do
    curl -fs -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "timed out waiting for $1" >&2
  return 1
}

# Each server runs in its own session, so cleanup can stop it with everything it started.
(
  cd "${repo}"
  export ARIA_ENV=test ARIA_DATABASE_URL="sqlite:///${data}/aria.db" ARIA_DATA_DIR="${data}" \
    ARIA_RATE_LIMIT_PER_MINUTE=100000 ARIA_LOG_FORMAT=console UV_NO_PROGRESS=1 \
    NVIDIA_API_KEY="" GEMINI_API_KEY="" gemini_api_key="" AZURE_OPENAI_API_KEY="" OPENAI_API_KEY="" \
    NIM_LOCAL_BASE_URL=""
  uv run aria db upgrade
  uv run aria seed --workers 2
) > "${data}/seed.log" 2>&1 || { cat "${data}/seed.log" >&2; exit 1; }

(
  cd "${repo}"
  export ARIA_ENV=test ARIA_DATABASE_URL="sqlite:///${data}/aria.db" ARIA_DATA_DIR="${data}" \
    ARIA_RATE_LIMIT_PER_MINUTE=100000 ARIA_LOG_FORMAT=console UV_NO_PROGRESS=1 \
    NVIDIA_API_KEY="" GEMINI_API_KEY="" gemini_api_key="" AZURE_OPENAI_API_KEY="" OPENAI_API_KEY="" \
    NIM_LOCAL_BASE_URL=""
  exec setsid uv run aria serve --port "${api_port}"
) > "${data}/api.log" 2>&1 &
groups+=("$!")
wait_for "${api}/readyz" || { cat "${data}/api.log" >&2; exit 1; }

(
  cd "${web}"
  ARIA_API_URL="${api}" NEXT_TELEMETRY_DISABLED=1 \
    exec setsid node node_modules/next/dist/bin/next start -p "${web_port}"
) > "${data}/web.log" 2>&1 &
groups+=("$!")
wait_for "${site}/api/healthz" || { cat "${data}/web.log" >&2; exit 1; }

# One run from the HDFS sample the console offers: triaged, approved and published, so the run
# view shows a finished run (a live one keeps an event stream open).
cd "${web}"
run_id=$(API="${api}" node --input-type=module - <<'JS'
import { readFileSync } from "node:fs";
const api = process.env.API;
const sample = JSON.parse(readFileSync("src/data/samples.json", "utf8")).find(
  (s) => s.system === "hdfs",
);
const post = async (path, body) => {
  const response = await fetch(api + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  return response.json();
};
const { run_id: id } = await post("/api/v1/runs", {
  system: sample.system,
  logs: sample.lines,
  synthetic: true,
});
let status = "";
for (let i = 0; i < 120 && status !== "awaiting_review"; i++) {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  status = (await (await fetch(`${api}/api/v1/runs/${id}`)).json()).status;
  if (status === "failed") throw new Error(`run ${id} failed`);
}
if (status !== "awaiting_review") throw new Error(`run ${id} is ${status}, not awaiting review`);
await post(`/api/v1/runs/${id}/review`, { decision: "approve", reviewer: "lighthouse" });
console.log(id);
JS
)
echo "run view: ${run_id}"

node scripts/lighthouse.mjs --base "${site}" --run "${run_id}"
