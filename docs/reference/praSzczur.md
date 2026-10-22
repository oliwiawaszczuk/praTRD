# Referencja: praSzczur — co przejmujemy

Źródło: `/Users/praoliwia/Desktop/Study/AI_MED/praSzczur` (MALDI-MSI, dojrzała appka, ~27k linii frontu + 3.2k sidecar).

## 1. Stack (przejmujemy 1:1)

| Warstwa | praSzczur | Uwagi dla praTRD |
|---|---|---|
| Shell desktop | Tauri v2 (Rust) | menu systemowe + własne menu „Workspace”, spawn/kill sidecara |
| Frontend | SvelteKit (adapter-static, `ssr=false`) + Svelte 5 runes, TS | identycznie |
| Backend obliczeń | Python FastAPI sidecar, port **7432**, uvicorn | praTRD potrzebuje **innego portu** (żeby obie appki mogły działać naraz) |
| Python env | `uv`, `.venv`, Python 3.14 lokalnie / 3.11 w CI | ujednolicić wersję w CI i lokalnie |
| Paczki front | `@fontsource/jetbrains-mono`, konva, marked, plotly | + biblioteka 3D (do decyzji) |
| Wykresy | Plotly | histogramy intensywności HU itp. |

## 2. Skrypty

- `dev.sh` → `cd app && pnpm tauri dev`
- `build.sh` → `pnpm tauri build` + kopiowanie `.app` do roota projektu
- `build.rs` zaszywa `PRASZCZUR_ROOT` (root projektu) w binarce na czas dev.
- `lib.rs`:
  - feature `pyinstaller-sidecar` → binarka PyInstaller z `resource_dir/sidecar/`, dane w `app_data_dir()`
  - bez feature → `uv run python sidecar/main.py` z rootem projektu (dev na macOS)
  - zabija proces na porcie przed startem, kill sidecara przy `WindowEvent::Destroyed`
  - **nie usuwać** pozycji z domyślnego menu Edytuj (Cmd+C/V w WKWebView)

## 3. Deploy / CI (`.github/workflows/release.yml`)

- Trigger: tag `v*.*.*`
- Macierz: `macos-14` (aarch64), `windows-latest` (x64 msvc), `ubuntu-22.04` (x64)
- Kroki: Rust + rust-cache → Node 22 + pnpm 9 → Python 3.11 + PyInstaller sidecar (`sidecar.spec`)
  → wstrzyknięcie binarki sidecara do `bundle.resources` (jq / pwsh) → deps Linux (webkit2gtk-4.1 …)
  → `pnpm tauri build -- --features pyinstaller-sidecar` → zip `.app` → `softprops/action-gh-release`
- Artefakty: macOS `.zip`, Windows `.exe`(NSIS) + `.msi`, Linux `.AppImage` + `.deb`
- **Do poprawy w praTRD:** PyInstaller ze stosem medycznym (SimpleITK/VTK/pydicom) będzie duży — `hiddenimports` i `excludes` trzeba przemyśleć od nowa; rozważyć `--onedir` zamiast onefile (szybszy start).

## 4. Wzorce architektoniczne (przejmujemy)

- **Workspace** — `workspace.svelte.ts`: `wsGet(key, fallback)` / `wsSet(key, value)`, cache w `$state`, zapis debounced 500 ms do sidecara (`/workspaces/{id}/settings`). Rejestr `workspaces/registry.json`, każdy ws w `workspaces/<id>/`. Eksport/import workspace'u.
- **Ustawienia globalne** — `appSettings.svelte.ts`: `getSetting/setSetting` → `app_settings.json`.
- **Wiele grafów per workspace** — `registry.json` + `<gid>.json`, autozapis 300 ms, `nodegraph_activeGraphId`.
- **Silnik grafu** (`nodegraph.ts`): typowane gniazda (`PortKind`), łączenie tylko przy identycznym `kind` (zero koercji), kolor kropki = kind, `NodeTypeDef {id: "domena/nazwa", domain, stage, inputs, outputs, params, evaluate, selectOutput}`, wykrywanie cykli, ewaluacja memoizowana raz per zmianę grafu (`$derived.by`), cache wyników po (wejście, parametry), ciężkie ops przez przycisk „Przetwórz”.
- **Ciężkie dane żyją w sidecarze**, do grafu trafia tylko id/uchwyt (wzorzec `macierz` z domeny Markery) — dla 3D to KLUCZOWE (wolumeny po 100+ MB).
- **Mosty między zakładkami** — `graphInsert.svelte.ts` („Wyślij do Node Graph”, duszek pod kursorem), `docsNav.svelte.ts` (ikonka (i) → Dokumentacja).
- **Zakładka Dokumentacja** — Markdown (`marked`), globalny tryb edycji, seed w kodzie + nadpisania w `app_docs.json`, opis node'a = jedno źródło (`getNodeDoc`).
- Tablica (Konva), Notatki, FloatingNotePad — opcjonalnie do przejęcia (pytanie w Q&A).
- Drag & drop przez Pointer Events, **nie** HTML5 DnD (niestabilne w webview Tauri).
- Ikony: ręcznie pisane inline SVG, `stroke="currentColor"`, **bez emoji**.

## 5. Styl UI → patrz `docs/design/ui-tokens.md`
