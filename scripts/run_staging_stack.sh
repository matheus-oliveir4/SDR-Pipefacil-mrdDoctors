#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE_PATH="${ENV_FILE:-.env.staging}"
UVICORN_BIN="${UVICORN_BIN:-$ROOT_DIR/.venv/bin/uvicorn}"
UVICORN_LOG_LEVEL="${UVICORN_LOG_LEVEL:-warning}"
UVICORN_ACCESS_LOG="${UVICORN_ACCESS_LOG:-false}"
APP_PID=""
TUNNEL_PID=""
source "$ROOT_DIR/scripts/env.sh"

ENV_FILE_PATH="$(resolve_env_file "$ROOT_DIR" "$ENV_FILE_PATH")"
LOCAL_ENV_FILE_PATH="$(env_local_file "$ENV_FILE_PATH")"

cleanup() {
  local exit_code=${1:-0}

  if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi

  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi

  exit "$exit_code"
}

handle_signal() {
  echo
  echo "Encerrando stack de staging..."
  cleanup 0
}

trap handle_signal INT TERM

if [[ ! -x "$UVICORN_BIN" ]]; then
  echo "uvicorn nao encontrado em $UVICORN_BIN. Rode make install primeiro." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE_PATH" ]]; then
  echo "Arquivo de ambiente nao encontrado: $ENV_FILE_PATH" >&2
  exit 1
fi

cd "$ROOT_DIR"

echo "Subindo API staging com $ENV_FILE_PATH"
if [[ -f "$LOCAL_ENV_FILE_PATH" ]]; then
  echo "Aplicando overrides locais de $LOCAL_ENV_FILE_PATH"
fi
UVICORN_ENV_ARGS=()
while IFS= read -r arg; do
  UVICORN_ENV_ARGS+=("$arg")
done < <(merged_env_args "$ENV_FILE_PATH" "$LOCAL_ENV_FILE_PATH")

UVICORN_RUNTIME_ARGS=(--reload --reload-include ".env*" --log-level "$UVICORN_LOG_LEVEL")
case "${UVICORN_ACCESS_LOG}" in
  true|TRUE|1|yes|YES)
    ;;
  *)
    UVICORN_RUNTIME_ARGS+=(--no-access-log)
    ;;
esac

"$UVICORN_BIN" app.main:app "${UVICORN_ENV_ARGS[@]}" "${UVICORN_RUNTIME_ARGS[@]}" &
APP_PID=$!

echo "Subindo tunnel staging"
ENV_FILE="$ENV_FILE_PATH" "$ROOT_DIR/scripts/run_dev_tunnel.sh" &
TUNNEL_PID=$!

while true; do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    wait "$APP_PID"
    APP_STATUS=$?
    echo "API staging encerrou com status $APP_STATUS." >&2
    cleanup "$APP_STATUS"
  fi

  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    wait "$TUNNEL_PID"
    TUNNEL_STATUS=$?
    echo "Tunnel staging encerrou com status $TUNNEL_STATUS." >&2
    cleanup "$TUNNEL_STATUS"
  fi

  sleep 1
done
