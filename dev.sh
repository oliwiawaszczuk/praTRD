#!/usr/bin/env bash
# praTRD dev mode: Vite hot-reload + Tauri; the sidecar runs from the project via uv.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
uv sync --frozen --quiet
cd app
[ -d node_modules ] || pnpm install --frozen-lockfile

echo "▶ praTRD dev (Ctrl+C aby zatrzymać)"
pnpm tauri dev
