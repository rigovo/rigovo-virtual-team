#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_HOST="${RIGOVO_API_HOST:-127.0.0.1}"
API_PORT="${RIGOVO_API_PORT:-8787}"
API_URL="http://${API_HOST}:${API_PORT}"
API_LOG="${ROOT_DIR}/.rigovo/e2e-api-flow.log"
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

find_open_port() {
  local start="${1:-8787}"
  python3 - "$start" <<'PY'
import socket
import sys
port = int(sys.argv[1])
for p in range(port, port + 200):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", p))
        print(p)
        break
    except OSError:
        pass
    finally:
        s.close()
else:
    print("")
PY
}

wait_for_task_visible() {
  local task_id="$1"
  local retries=40
  for ((i=1; i<=retries; i++)); do
    local body
    body="$(curl -fsS "${API_URL}/v1/tasks/${task_id}/detail" || true)"
    if python3 - "${task_id}" "${body}" <<'PY'
import json
import sys
task_id = sys.argv[1]
try:
    doc = json.loads(sys.argv[2])
except Exception:
    sys.exit(1)
if doc.get("id") == task_id and "status" in doc:
    sys.exit(0)
sys.exit(1)
PY
    then
      return 0
    fi
    sleep 1
  done
  return 1
}

assert_expr() {
  local json_body="$1"
  local expr="$2"
  python3 - "${expr}" "${json_body}" <<'PY'
import json
import sys
expr = sys.argv[1]
doc = json.loads(sys.argv[2])
safe_builtins = {
    "bool": bool,
    "isinstance": isinstance,
    "list": list,
    "dict": dict,
    "set": set,
    "len": len,
}
ok = eval(expr, {"__builtins__": safe_builtins}, {"doc": doc})
if not ok:
    raise SystemExit(1)
PY
}

mkdir -p "${ROOT_DIR}/.rigovo"
trap cleanup EXIT INT TERM

selected_port="$(find_open_port "${API_PORT}")"
if [[ -z "${selected_port}" ]]; then
  echo "[rigovo-e2e-api] no free local API port found"
  exit 1
fi
if [[ "${selected_port}" != "${API_PORT}" ]]; then
  echo "[rigovo-e2e-api] warning: preferred port ${API_PORT} in use, falling back to ${selected_port}"
fi
API_PORT="${selected_port}"
API_URL="http://${API_HOST}:${API_PORT}"

echo "[rigovo-e2e-api] starting API at ${API_URL}"
(
  cd "${ROOT_DIR}"
  # Dummy keys let pre-flight pass in headless e2e without real provider creds.
  PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}" \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-dummy-e2e-key}" \
  OPENAI_API_KEY="${OPENAI_API_KEY:-dummy-e2e-key}" \
  RIGOVO_API_PORT="${API_PORT}" \
  python3 -m rigovo.main serve --host "${API_HOST}" --port "${API_PORT}" --project "${ROOT_DIR}"
) >"${API_LOG}" 2>&1 &
API_PID=$!

sleep 0.5
if ! kill -0 "${API_PID}" >/dev/null 2>&1; then
  echo "[rigovo-e2e-api] API process died immediately. Log output:"
  tail -n 40 "${API_LOG}" 2>/dev/null || true
  exit 1
fi

if ! wait_for_health; then
  echo "[rigovo-e2e-api] API failed health check"
  tail -n 120 "${API_LOG}" || true
  exit 1
fi

echo "[rigovo-e2e-api] creating task"
create_body="$(curl -fsS -X POST "${API_URL}/v1/tasks" \
  -H "Content-Type: application/json" \
  -d '{"description":"E2E: validate lifecycle controls"}')"
assert_expr "${create_body}" "doc.get('status') == 'created' and bool(doc.get('task_id'))"
task_id="$(python3 - "${create_body}" <<'PY'
import json
import sys
print(json.loads(sys.argv[1])["task_id"])
PY
)"

echo "[rigovo-e2e-api] waiting for task visibility: ${task_id}"
if ! wait_for_task_visible "${task_id}"; then
  echo "[rigovo-e2e-api] task did not appear in detail endpoint"
  tail -n 120 "${API_LOG}" || true
  exit 1
fi

detail_body="$(curl -fsS "${API_URL}/v1/tasks/${task_id}/detail")"
assert_expr "${detail_body}" "doc.get('id') == '${task_id}' and isinstance(doc.get('steps', []), list)"

audit_body="$(curl -fsS "${API_URL}/v1/tasks/${task_id}/audit")"
assert_expr "${audit_body}" "doc.get('task_id') == '${task_id}' and isinstance(doc.get('entries', []), list)"

echo "[rigovo-e2e-api] aborting task"
abort_body="$(curl -fsS -X POST "${API_URL}/v1/tasks/${task_id}/abort" \
  -H "Content-Type: application/json" \
  -d '{"reason":"e2e abort check","actor":"e2e"}')"
assert_expr "${abort_body}" "doc.get('status') == 'aborted'"

echo "[rigovo-e2e-api] resuming task"
resume_body="$(curl -fsS -X POST "${API_URL}/v1/tasks/${task_id}/resume" \
  -H "Content-Type: application/json" \
  -d '{"resume_now":true,"actor":"e2e"}')"
assert_expr "${resume_body}" "doc.get('status') in {'resuming','already_running'}"

echo "[rigovo-e2e-api] validating inbox visibility"
inbox_body="$(curl -fsS "${API_URL}/v1/ui/inbox")"
assert_expr "${inbox_body}" "isinstance(doc, list)"
python3 - "${task_id}" "${inbox_body}" <<'PY'
import json
import sys
task_id = sys.argv[1]
rows = json.loads(sys.argv[2])
if not any(r.get("id") == task_id for r in rows):
    raise SystemExit(1)
PY

echo "[rigovo-e2e-api] PASS"
