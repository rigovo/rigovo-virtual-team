#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_HOST="${RIGOVO_API_HOST:-127.0.0.1}"
API_PORT="${RIGOVO_API_PORT:-8787}"
API_URL="http://${API_HOST}:${API_PORT}"
API_LOG="${ROOT_DIR}/.rigovo/e2e-runtime-api.log"
API_PID=""

cleanup() {
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi
}

wait_for_health() {
  local retries=30
  for ((i=1; i<=retries; i++)); do
    if curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

assert_json() {
  local endpoint="$1"
  local expr="$2"
  local body
  body="$(curl -fsS "${API_URL}${endpoint}")"
  python3 - "${expr}" "${body}" <<'PY'
import json
import sys
expr = sys.argv[1]
doc = json.loads(sys.argv[2])
ok = eval(expr, {"__builtins__": {}}, {"doc": doc})
if not ok:
    print(f"assertion failed: {expr}", file=sys.stderr)
    sys.exit(1)
PY
}

mkdir -p "${ROOT_DIR}/.rigovo"
trap cleanup EXIT INT TERM

echo "[rigovo-e2e-runtime] starting API at ${API_URL}"
(
  cd "${ROOT_DIR}"
  RIGOVO_API_PORT="${API_PORT}" python3 -m rigovo.main serve --host "${API_HOST}" --port "${API_PORT}" --project "${ROOT_DIR}"
) >"${API_LOG}" 2>&1 &
API_PID=$!

if ! wait_for_health; then
  echo "[rigovo-e2e-runtime] API failed health check"
  tail -n 120 "${API_LOG}" || true
  exit 1
fi

echo "[rigovo-e2e-runtime] verifying runtime capabilities and core UI APIs"
assert_json "/v1/runtime/capabilities" "'orchestration' in doc and 'plugins' in doc and 'runtime' in doc"
assert_json "/v1/runtime/capabilities" "doc['runtime'].get('filesystem_sandbox') == 'project_root'"
assert_json "/v1/memory/metrics" "'total_memories' in doc and 'utilization_rate' in doc"
assert_json "/v1/control/state" "'workspace' in doc and 'policy' in doc"
assert_json "/v1/ui/inbox" "isinstance(doc, list)"
assert_json "/v1/ui/approvals" "isinstance(doc, list)"

echo "[rigovo-e2e-runtime] PASS"
