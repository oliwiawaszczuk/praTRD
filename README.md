# praTRD

Desktopowa aplikacja do pracy z danymi DICOM w 3D, z pipeline'ami budowanymi jako graf node'ów.
Tauri v2 + SvelteKit 3 / Svelte 5 + sidecar Python 3.13 (FastAPI) + vtk.js.

## Co potrafi (0.1.0)

- **Dane:** import DICOM (także DICOM-SEG), NIfTI, NRRD, MHA; anonimizacja przy imporcie; biblioteka serii per workspace, przeglądarka tagów.
- **Scena:** 3 przekroje + 3D (ray casting), wspólny kursor, okno/poziom na histogramie, presety 3D, płaszczyzny przekrojów w 3D, gizmo, orto/perspektywa.
- **Graf node'ów:** wolumen (seria, przycinanie boxem 3D, resampling, wygładzanie), segmentacja (próg na żywo, Otsu, region growing, pędzel/gumka/nożyce w 2D i 3D, logika, morfologia, wyspy, labelmapy), pomiary (markupy, statystyki segmentu, histogram, profil). Podgląd na żywo + pełna rozdzielczość w tle, wyniki w cache.
- **Wyniki:** tabele z wykresami, eksport CSV (polski Excel), zrzuty widoków na **Tablicę**.
- **Tablica, Notatki (pływający notatnik), Dokumentacja** (poradnik + opisy node'ów), okno skrótów (**?**).

## Instalacja (wydanie z GitHuba)

Instalatory nie są podpisane certyfikatem dewelopera:

- **macOS:** rozpakuj `praTRD-macOS-aarch64.zip`, przenieś `praTRD.app` do Programów, potem jednorazowo
  `xattr -dr com.apple.quarantine /Applications/praTRD.app` (albo PPM → Otwórz).
- **Windows:** `.exe` (NSIS) albo `.msi`; przy ostrzeżeniu SmartScreen: „Więcej informacji” → „Uruchom mimo to”.
- **Linux:** `.AppImage` (`chmod +x`) albo `.deb`.

Dane aplikacji (workspace'y, cache wyników, notatki, tablice) są w folderze danych użytkownika
(macOS: `~/Library/Application Support/com.praoliwia.praTRD`).

## Rozwój

Wymagania: `uv`, `pnpm`, Rust (stable), Node LTS.

```bash
uv sync && (cd app && pnpm install)
./dev.sh                  # tryb deweloperski
./build.sh --standalone   # samodzielny praTRD.app (macOS)
uv run python scripts/bench_large.py dicom|nifti   # wydajność na dużych danych
```

Instalatory na macOS, Windows i Linux buduje `.github/workflows/release.yml` po wypchnięciu tagu `v*.*.*`.

Dokumentacja: `docs/02-plan.md` (plan i etapy), `CLAUDE.md` (konwencje), `CHANGELOG.md`.
