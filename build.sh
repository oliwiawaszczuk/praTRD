#!/usr/bin/env bash
# Local macOS build → praTRD.app in the project root.
#
#   ./build.sh               fast: the app runs the sidecar via uv from this project
#                            (data in ./workspaces) — same as praSzczur's build
#   ./build.sh --no-install  build only (praTRD.app stays in the project root)
#   ./build.sh --install-only  copy the last build to /Applications (app must be closed)
#   ./build.sh --standalone  release-like: frozen PyInstaller sidecar bundled inside the
#                            .app, data in ~/Library/Application Support/com.praoliwia.praTRD
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/app"
DEST="$ROOT/praTRD.app"
INSTALLED="/Applications/praTRD.app"
INSTALL=1
STANDALONE=0
for a in "$@"; do
  case "$a" in
    --no-install) INSTALL=0 ;;
    --standalone) STANDALONE=1 ;;
    --install-only)
      [ -d "$DEST" ] || { echo "Brak $DEST — najpierw ./build.sh"; exit 1; }
      pgrep -f "$INSTALLED/Contents/MacOS/" >/dev/null 2>&1 && { echo "⚠ Zamknij praTRD (⌘Q) i spróbuj ponownie"; exit 1; }
      rm -rf "$INSTALLED"
      ditto "$DEST" "$INSTALLED"
      echo "✓ Zainstalowano: $INSTALLED"
      exit 0 ;;
  esac
done
cd "$ROOT"
uv sync --frozen --quiet

ARGS=(--bundles app)
if [ "$STANDALONE" = 1 ]; then
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

if [ "$INSTALL" = 1 ]; then
  # An app that is running keeps its old files open: ask to quit it first.
  if pgrep -f "$INSTALLED/Contents/MacOS/" >/dev/null 2>&1; then
    echo "⚠ praTRD jest uruchomiony — zamknij go (⌘Q) i uruchom: ./build.sh --install-only"
    exit 0
  fi
  echo "▶ Instalacja w /Applications…"
  rm -rf "$INSTALLED"
  ditto "$DEST" "$INSTALLED"
  echo "✓ Zainstalowano: $INSTALLED"
fi
