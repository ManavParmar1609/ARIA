#!/usr/bin/env bash
# Smoke-test a running stack (`make up`): health and readiness, then one triage run through the
# worker to the review pause, an approval, and the published report.
set -euo pipefail

base="${ARIA_URL:-http://127.0.0.1:8000}"
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}127.0.0.1,localhost"  # never send local calls to a proxy
auth=()
if [[ -n "${ARIA_API_KEY:-}" ]]; then
  auth=(-H "Authorization: Bearer ${ARIA_API_KEY}")
fi

json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }

curl -fsS "${base}/healthz" >/dev/null
curl -fsS "${base}/readyz" >/dev/null
echo "healthy: ${base}"

# A small brute-force window in OpenSSH's own format (synthetic, generated here).
payload=$(python3 - <<'PY'
import json
from datetime import datetime, timedelta

start = datetime(2026, 3, 2, 9, 0)
lines = []
for i in range(180):
    ts = start + timedelta(seconds=2 * i)
    stamp = f"{ts:%b} {ts.day:2d} {ts:%H:%M:%S}"
    if i % 9 == 0:
        msg = f"Accepted password for deploy from 198.51.100.{i % 7 + 2} port {40000 + i} ssh2"
    else:
        msg = f"Failed password for invalid user user{i % 23} from 203.0.113.9 port {50000 + i} ssh2"
    lines.append(f"{stamp} LabSZ sshd[{24000 + i % 5}]: {msg}")
print(json.dumps({"system": "openssh", "logs": lines, "title": "Smoke test", "synthetic": True}))
PY
)

run_id=$(curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -d "${payload}" \
  "${base}/api/v1/runs" | json '["run_id"]')
echo "run ${run_id} accepted"

status=""
for _ in $(seq 1 180); do
  status=$(curl -fsS "${auth[@]}" "${base}/api/v1/runs/${run_id}" | json '["status"]')
  [[ "${status}" == "awaiting_review" || "${status}" == "failed" ]] && break
  sleep 1
done
if [[ "${status}" != "awaiting_review" ]]; then
  echo "run ${run_id} ended in '${status}', expected awaiting_review" >&2
  exit 1
fi

valid=$(curl -fsS "${auth[@]}" "${base}/api/v1/runs/${run_id}/report" | json '["report"]["validation"]["ok"]')
[[ "${valid}" == "True" ]] || { echo "report failed validation" >&2; exit 1; }

final=$(curl -fsS "${auth[@]}" -H 'Content-Type: application/json' \
  -d '{"decision": "approve", "reviewer": "smoke-test"}' \
  "${base}/api/v1/runs/${run_id}/review" | json '["status"]')
[[ "${final}" == "published" ]] || { echo "review left the run in '${final}'" >&2; exit 1; }
echo "run ${run_id}: triaged, reviewed and published"
