#!/usr/bin/env bash
# Local macOS build → praTRD.app in the project root.
#
#   ./build.sh               fast: the app runs the sidecar via uv from this project
#                            (data in ./workspaces) — same as praSzczur's build
#   ./build.sh --standalone  release-like: frozen PyInstaller sidecar bundled inside the
#                            .app, data in ~/Library/Application Support/com.praoliwia.praTRD
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/app"
DEST="$ROOT/praTRD.app"
cd "$ROOT"
uv sync --frozen --quiet

ARGS=(--bundles app)
if [[ "${1:-}" == "--standalone" ]]; then
  ./scripts/build-sidecar.sh
  ARGS+=(--config src-tauri/tauri.standalone.conf.json --features pyinstaller-sidecar)
fi

echo "▶ Budowanie praTRD.app…"
cd "$APP"
[ -d node_modules ] || pnpm install --frozen-lockfile
pnpm tauri build "${ARGS[@]}"

echo "▶ Kopiowanie do roota projektu…"
rm -rf "$DEST"
cp -R "$APP/src-tauri/target/release/bundle/macos/praTRD.app" "$DEST"
echo "✓ Gotowe: $DEST"
