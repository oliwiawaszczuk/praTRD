# praTRD

Desktopowa aplikacja do pracy z danymi DICOM w 3D, z pipeline'ami budowanymi jako graf node'ów.
Tauri v2 + SvelteKit 3 / Svelte 5 + sidecar Python 3.13 (FastAPI) + vtk.js.

## Start

Wymagania: `uv`, `pnpm`, Rust (stable), Node LTS.

```bash
uv sync && (cd app && pnpm install)
./dev.sh                  # tryb deweloperski
./build.sh --standalone   # samodzielny praTRD.app (macOS)
```

Instalatory na macOS, Windows i Linux buduje `.github/workflows/release.yml` po wypchnięciu tagu `v*.*.*`.

Dokumentacja: `docs/02-plan.md` (plan i etapy), `CLAUDE.md` (konwencje), `CHANGELOG.md`.
