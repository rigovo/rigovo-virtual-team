#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_HOST="${RIGOVO_API_HOST:-127.0.0.1}"
API_PORT="${RIGOVO_API_PORT:-8787}"
API_URL="http://${API_HOST}:${API_PORT}"
API_LOG="${ROOT_DIR}/.rigovo/e2e-api.log"
API_PID=""
E2E_INSTALL="${RIGOVO_E2E_INSTALL:-auto}" # auto|always|never

cleanup() {
  echo "[rigovo-e2e] cleaning up..."
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" >/dev/null 2>&1; then
    kill "${API_PID}" >/dev/null 2>&1 || true
    wait "${API_PID}" >/dev/null 2>&1 || true
  fi
}

wait_for_health() {
  local retries=30
  local delay=1
  local i
  for ((i=1; i<=retries; i++)); do
    if curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

find_open_port() {
  local start="${1:-8787}"
  python3 - "$start" <<'PY'
import socket, sys
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

check_env_var() {
  local var_name="$1"
  local env_file="${ROOT_DIR}/.env"
  grep -q "^${var_name}=" "${env_file}" 2>/dev/null && return 0
  return 1
}

start_api() {
  API_URL="http://${API_HOST}:${API_PORT}"
  echo "[rigovo-e2e] starting control-plane API at ${API_URL}"
  (
    cd "${ROOT_DIR}"
    RIGOVO_API_PORT="${API_PORT}" python3 -m rigovo.main serve --host "${API_HOST}" --port "${API_PORT}" --project "${ROOT_DIR}"
  ) >"${API_LOG}" 2>&1 &
  API_PID=$!

  sleep 0.5
  if ! kill -0 "${API_PID}" >/dev/null 2>&1; then
    echo "[rigovo-e2e] API process died immediately. Log output:"
    tail -n 40 "${API_LOG}" 2>/dev/null || true
    exit 1
  fi
}

echo "[rigovo-e2e] project root: ${ROOT_DIR}"

# ── Prerequisites ──
for cmd in python3 pnpm node curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[rigovo-e2e] missing required command: $cmd"
    exit 1
  fi
done

# Create .env if it doesn't exist (optional — for dev overrides only)
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  touch "${ROOT_DIR}/.env"
fi

# WorkOS Client ID is embedded in the app (public, safe to ship).
# API key is optional — only needed for org/role admin features.
if check_env_var "WORKOS_API_KEY"; then
  echo "[rigovo-e2e] WORKOS_API_KEY found — org/role admin features enabled"
else
  echo "[rigovo-e2e] WORKOS_API_KEY not set — auth works via PKCE, admin features disabled"
fi

# ── Install deps if needed ──
if [[ "${E2E_INSTALL}" == "always" ]] || [[ "${E2E_INSTALL}" == "auto" && ! -d "${ROOT_DIR}/apps/desktop/node_modules" ]]; then
  echo "[rigovo-e2e] installing desktop dependencies"
  pnpm -C "${ROOT_DIR}/apps/desktop" install --no-frozen-lockfile --prefer-offline
elif [[ "${E2E_INSTALL}" == "never" ]]; then
  echo "[rigovo-e2e] skipping install (RIGOVO_E2E_INSTALL=never)"
fi

mkdir -p "${ROOT_DIR}/.rigovo"

trap cleanup EXIT INT TERM

# ── Start API (prefer fixed port 8787 for stable WorkOS callback URI) ──
selected_port="$(find_open_port "${API_PORT}")"
if [[ -z "${selected_port}" ]]; then
  echo "[rigovo-e2e] no free local API port found"
  exit 1
fi
if [[ "${selected_port}" != "${API_PORT}" ]]; then
  echo "[rigovo-e2e] warning: preferred port ${API_PORT} in use, falling back to ${selected_port}"
  echo "[rigovo-e2e] update WorkOS callback URI if needed"
fi
API_PORT="${selected_port}"
API_URL="http://${API_HOST}:${API_PORT}"
CALLBACK_URI="http://127.0.0.1:${API_PORT}/v1/auth/callback"
start_api

if ! wait_for_health; then
  echo "[rigovo-e2e] API failed health check after 30s. tailing logs:"
  tail -n 120 "${API_LOG}" || true
  exit 1
fi

echo "[rigovo-e2e] API healthy at ${API_URL}"
echo "[rigovo-e2e] logs: ${API_LOG}"

# ── Launch Electron desktop app ──
echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  Rigovo Desktop — Local Development                 │"
echo "  │                                                     │"
echo "  │  API:      ${API_URL}                       │"
echo "  │  Callback: ${CALLBACK_URI}  │"
echo "  │                                                     │"
echo "  │  Register this callback URI in WorkOS Dashboard:    │"
echo "  │  https://dashboard.workos.com → Redirects           │"
echo "  └─────────────────────────────────────────────────────┘"
echo ""
VITE_RIGOVO_API="${API_URL}" RIGOVO_API_PORT="${API_PORT}" pnpm -C "${ROOT_DIR}/apps/desktop" run dev
