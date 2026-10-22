#!/usr/bin/env bash
# Freezes the Python sidecar with PyInstaller (--onedir) into app/sidecar/dist/sidecar/
# and smoke-tests the binary: it must start and report every dependency + DICOM decoder.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▶ PyInstaller: sidecar"
uv run --frozen pyinstaller app/sidecar/sidecar.spec --noconfirm --log-level WARN \
  --distpath app/sidecar/dist --workpath app/sidecar/build

uv run --frozen python scripts/smoke_sidecar.py app/sidecar/dist/sidecar
