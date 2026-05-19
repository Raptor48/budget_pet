#!/usr/bin/env bash
# Backend-only local-dev launcher: FastAPI on :8000 with --reload.
# Loads .env, ensures .venv exists with pinned requirements, then uvicorn.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"

command -v python3 >/dev/null || { echo "❌ python3 not found"; exit 1; }

if [ ! -f .env ]; then
    echo "❌ .env missing in $ROOT — copy .env.template and fill it in"
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ -z "${DATABASE_URL:-}" ]; then
    echo "❌ DATABASE_URL is empty — fill it in .env"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "🐍 Creating .venv…"
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip --quiet
fi
PY=".venv/bin/python"
PIP=".venv/bin/pip"

STAMP=".venv/.requirements-stamp"
if ! "$PY" -c "import fastapi, uvicorn, asyncpg, starlette" 2>/dev/null \
   || [ requirements.txt -nt "$STAMP" ]; then
    echo "📦 Installing Python dependencies into .venv…"
    "$PIP" install -q -r requirements.txt
    touch "$STAMP"
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "🚀 FastAPI → http://localhost:$API_PORT  (docs: /docs)"
echo "   Ctrl+C to stop"
echo ""

exec "$PY" -m uvicorn web.main:app \
    --host 0.0.0.0 \
    --port "$API_PORT" \
    --reload \
    --reload-dir web
