#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_DIR/.env"
if [ ! -f "$CONFIG_FILE" ]; then
  printf 'Создай %s по образцу .env.example.\n' "$CONFIG_FILE" >&2
  exit 1
fi

export MULTICODEX_PROJECT_DIR="$PROJECT_DIR"
# .env is a local shell file containing quoted path assignments.
set -a
source "$CONFIG_FILE"
set +a
: "${PYTHON:?Укажи PYTHON в .env}"
exec "$PYTHON" "$PROJECT_DIR/scripts/accounts.py" "$@"
