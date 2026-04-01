#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_PORT="${HTTP_PORT:-8080}"
BACKEND_HOST="${HTTP_HOST:-0.0.0.0}"
MODE="${1:-prod}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2./口
    exit 1
  fi
}

cleanup() {
  local exit_code=$?
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  wait >/dev/null 2>&1 || true
  exit "$exit_code"
}

start_backend() {
  printf 'Starting backend on %s:%s...\n' "$BACKEND_HOST" "$BACKEND_PORT"
  (
    cd "$ROOT_DIR"
    source .venv/bin/activate
    HTTP_HOST="$BACKEND_HOST" HTTP_PORT="$BACKEND_PORT" python main.py
  ) &
  BACKEND_PID=$!
}

start_frontend_dev() {
  printf 'Starting frontend dev server...\n'
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --host 0.0.0.0
  ) &
  FRONTEND_PID=$!
}

run_prod() {
  printf 'Installing frontend dependencies...\n'
  (
    cd "$FRONTEND_DIR"
    npm install
  )
  printf 'Building frontend...\n'
  (
    cd "$FRONTEND_DIR"
    npm run build
  )
  start_backend
  printf 'Production-style mode ready. Open http://localhost:%s/\n' "$BACKEND_PORT"
  wait "$BACKEND_PID"
}

run_dev() {
  start_backend
  start_frontend_dev
  printf 'Dev-split mode ready. Frontend: http://localhost:5173/  Backend API: http://localhost:%s/\n' "$BACKEND_PORT"
  wait "$BACKEND_PID" "$FRONTEND_PID"
}

print_help() {
  cat <<'EOF'
Usage:
  ./run.sh         Build frontend and run Python server
  ./run.sh prod    Same as default
  ./run.sh dev     Run Python server and Vite dev server together
  ./run.sh help    Show this help
EOF
}

require_command npm
require_command python

if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  printf 'Missing virtual environment at .venv\n' >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR" ]]; then
  printf 'Missing frontend directory at %s\n' "$FRONTEND_DIR" >&2
  exit 1
fi

trap cleanup INT TERM EXIT

case "$MODE" in
  prod)
    run_prod
    ;;
  dev)
    run_dev
    ;;
  help|-h|--help)
    print_help
    ;;
  *)
    printf 'Unknown mode: %s\n\n' "$MODE" >&2
    print_help >&2
    exit 1
    ;;
esac
