#!/usr/bin/env bash
# Frontend-only local-dev launcher: Next.js (Turbopack) on :3000.
# Loads root .env so NEXT_PUBLIC_* vars stay in sync with the API process.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WEB_PORT="${WEB_PORT:-3000}"

command -v npm >/dev/null || { echo "❌ npm not found"; exit 1; }

# Load root .env so NEXT_PUBLIC_API_URL etc. propagate. frontend/.env.local
# layers on top via Next.js's own loader, which is the right place for
# frontend-specific overrides.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [ ! -d frontend/node_modules ]; then
    echo "📦 Installing npm dependencies…"
    (cd frontend && npm install)
fi

echo "🚀 Next.js → http://localhost:$WEB_PORT"
echo "   Ctrl+C to stop"
echo ""

cd frontend
exec npm run dev -- --port "$WEB_PORT"
