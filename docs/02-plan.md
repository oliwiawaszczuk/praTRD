# praTRD: plan fundamentu aplikacji

Status: **ZATWIERDZONY** (2026-10-22). Decyzje źródłowe: `01-qa.md`. Postęp: `CHANGELOG.md`.

> Korekty po E5: zamiast node'a `pomiary/eksport` — przycisk **CSV przy każdej tabeli** (okno
> tabeli, zapis przez systemowe „Zapisz jako”; CSV pod polski Excel: `;`, przecinek dziesiętny);
> wykresy w SVG zamiast Plotly (lżejsze, kilkaset punktów); markupy też w 3D (stawianie na
> powierzchni), ROI tylko w 2D; powierzchnia segmentu z marching cubes po wygładzeniu σ 0,6 woksela.
>
> Korekty po E4: edycja pędzlem zapisuje pociągnięcia (kule w mm), a nie maskę-deltę —
> mniejsze, odtwarzalne przy każdej zmianie wejścia/rozdzielczości. RTSTRUCT (kontury) — później.
> Próg w 2D liczony na żywo w shaderze. Region growing domyślnie „tolerancja” od ziarna.
>
> Korekty po E3: usuwanie node'ów bez potwierdzenia (jest cofnij/ponów — pewniejsze niż modal);
> wyniki pośrednie zawsze zapisywane do cache (zarr + piramida) — prostsze i trwałe między
> sesjami, kosztem ~0,6 s zapisu na node w pełnej rozdzielczości; ewentualna optymalizacja
> (tylko RAM dla niewyświetlanych) później, jeśli okaże się potrzebna.
>
> Korekty po E2: **widoki 2D nie używają vtk.js**, tylko własnego renderera WebGL2 z przekrojami
> strumieniowanymi z sidecara (pełna rozdzielczość niezależnie od rozmiaru wolumenu; vtk.js
> wymagałby całego wolumenu w GPU). vtk.js zostaje dla 3D. Rekonstrukcje skośne (oblique MPR)
> — później (sidecar może liczyć reslice). Kursor/krzyż jest w 2D; w widoku 3D jeszcze nie.
>
> Korekty po E1: import DICOM-SEG / RTSTRUCT przeniesiony do **E4** (to segmentacje, potrzebują
> modelu labelmap z E4); import STL — razem z domeną Mesh (po 0.1). Zakładka Dane ma już podgląd
> przekrojów 2D (szybka weryfikacja importu), pełne viewporty nadal w E2.
>
> Korekty po E0: Python **3.13** (nie 3.12); port sidecara **dynamiczny** (nie stały 7433); SvelteKit 3 → importy `#lib/…`; dodany watchdog procesu rodzica.

---

## 1. Architektura w skrócie

```
┌──────────────────────────── Tauri v2 (Rust) ─────────────────────────────┐
│  okno, menu (Workspace), spawn/kill sidecara, dialogi plików               │
│ ┌──────────────── WebView: SvelteKit + Svelte 5 (TS) ───────────────────┐ │
│ │  Zakładki: Dane │ Scena │ Tablica │ Notatki │ Dokumentacja │ Ustawienia│ │
│ │  Scena = [Viewporty vtk.js: 3D + MPR] / [Edytor Node Graph] / [Panel] │ │
│ │  Front trzyma: definicję grafu, stan UI, KAFLE do wyświetlenia        │ │
│ └───────────────▲──────────────────── HTTP (JSON + binarne) + WebSocket ┘ │
└─────────────────┼──────────────────────────────────────────────────────────┘
                  │ 127.0.0.1:<port dynamiczny>
┌─────────────────┴─────── Python sidecar (FastAPI, uv) ─────────────────────┐
│  io: DICOM (pydicom + SimpleITK), anonimizacja, NIfTI/NRRD, DICOM-SEG      │
│  store: multiskalowy, kafelkowany magazyn wolumenów (Zarr)                 │
│  graph: rejestr typów node'ów + ewaluator + cache wyników + joby w tle     │
│  nodes/: segmentacja, pomiary, (wolumen), (mesh), (ai)                    │
└────────────────────────────────────────────────────────────────────────────┘
dysk: workspaces/<wid>/{series/, store/, cache/, nodegraphs/, settings.json}
```

**Zasada nr 1 (z praSzczur, zaostrzona):** ciężkie dane żyją wyłącznie w sidecarze. Graf i front operują na **uchwytach** (`VolumeRef`, `LabelmapRef`, `MeshRef`). Do przeglądarki trafiają tylko kafle i plastry w rozdzielczości, która jest aktualnie widoczna.

**Zasada nr 2 (różnica względem praSzczur):** w praSzczur graf liczy się w przeglądarce (TS `evaluate`). W praTRD **typy node'ów i ewaluacja są w Pythonie**. Front pobiera schemat typów (`GET /node-types`: porty, parametry, opisy) i renderuje UI node'a generycznie z tego schematu. Typ node'a ma jedno źródło prawdy, a ciężkie obliczenia nigdy nie wchodzą do webview.

---

## 2. Decyzja: renderer 3D

**Wybór: vtk.js (WebGL2) za własną warstwą abstrakcji `ViewportEngine`.**

| Kryterium | vtk.js | własny silnik (three.js / WebGPU / C++) |
|---|---|---|
| Ray casting wolumenu, transfer functions, presety CT/MR | gotowe, sprawdzone (OHIF, Slicer web, VolView) | miesiące pracy, zanim dorówna |
| MPR (reslice dowolnej płaszczyzny), labelmapy, meshe, picking | gotowe | do napisania |
| Wydajność | GPU ray casting; ograniczają ją rozmiar tekstury 3D i VRAM, a to i tak rozwiązuje LOD (§3) | ten sam limit GPU |
| Osadzenie w Tauri | natywnie w webview | C++/OpenGL: osobne okno lub offscreen, problemy na 3 systemach |
| Rozwój | Kitware rozwija backend WebGPU | – |

Wniosek: przy danych medycznych „najszybciej i najlepszy efekt” daje biblioteka. Własny silnik nie da lepszego obrazu, a opóźni projekt o miesiące. Na przyszłość zostaje furtka: cała aplikacja rozmawia z interfejsem `ViewportEngine` (`setVolume`, `setLabelmap`, `setMesh`, `setSlicePlane`, `setTransferFunction`, `pick`, `screenshot`), a nie z vtk.js bezpośrednio. Gdyby kiedyś powstał własny renderer WebGPU (praHand3D v2), wystarczy dopisać drugą implementację.

Cornerstone3D (też na vtk.js) odrzucony jako fundament: ma własny model danych i ładowania DICOM, który kłóci się z naszym grafem w sidecarze. Można z niego podglądać rozwiązania narzędzi (pędzel, progowanie w viewporcie).

**Ryzyko:** WebKitGTK na Linuksie ma słabsze WebGL2 niż WebView2 (Windows) i WKWebView (macOS). Linux jest wspierany, ale nie jest platformą referencyjną dla wydajności.

---

## 3. Duże dane: strategia od pierwszego dnia

1. **Import, czyli konwersja do magazynu.** Seria DICOM (lub NIfTI/NRRD) jest raz czytana i zapisywana do `workspaces/<wid>/store/<vid>.zarr`:
   - typ natywny (np. int16), kafle 64³, kompresja zstd (blosc);
   - **piramida rozdzielczości** (level 0 = pełna, kolejne ×2 w dół, aż do ≤ 128³);
   - metadane: `shape`, `spacing`, `origin`, `direction` (IJK→LPS), modalność, rescale slope/intercept już zastosowane, okno domyślne, statystyki/histogram.
   - Import jest **jobem** z postępem (WebSocket) i można go anulować.
2. **Front pobiera tylko to, co widzi:**
   - MPR: `GET /volumes/{vid}/slice?axis|plane&index&level` → binarny plaster; level dobierany do rozmiaru viewportu i zoomu;
   - 3D: wolumen na poziomie piramidy mieszczącym się w budżecie GPU (ustawienie globalne, np. 256³ / 512³), a po zatrzymaniu kamery opcjonalnie wyższy level dla ROI;
   - transfer binarny: `application/octet-stream` + metadane w nagłówkach (bez JSON-a z liczbami jak w praSzczur).
3. **Ewaluacja grafu w dwóch rozdzielczościach (to też realizuje „Hybrydę”):**
   - **podgląd**: lekkie node'y liczą się na żywo na zmniejszonym levelu (np. ≤ 256³), w ułamku sekundy;
   - **pełna rozdzielczość**: na żądanie („Przetwórz”) lub automatycznie po bezczynności, jako job w tle.
4. **Cache wyników:** klucz = hash(typ node'a, parametry, klucze wejść, level). Wyniki trafiają do `cache/` jako zarr, w RAM jest LRU z limitem pamięci (ustawienie globalne). Zmiana parametru unieważnia tylko node'y w dół grafu.
5. **Pamięć:** operacje kafelkowalne (próg, logika masek, statystyki) idą kafel po kaflu i nie ładują całego wolumenu. Operacje globalne (SimpleITK: region growing, morfologia z dużym promieniem) ładują cały level do RAM; gdy przekracza on limit, UI proponuje ROI/crop albo niższy level.

---

## 4. Model danych grafu (typy gniazd)

| `PortKind` | Co to | Kolor |
|---|---|---|
| `wolumen` | skalarny wolumen 3D (CT/MR/PET…) + geometria | `#5b9bd5` |
| `segmentacja` | labelmap z tabelą segmentów (nazwa, kolor, id) | `#b48ce0` |
| `segment` | pojedyncza maska binarna | `#7bc47f` |
| `punkty` | markupy: punkty/linie/kąty/ROI w mm (LPS) | `#f2994a` |
| `tabela` | wynik pomiarów/statystyk (kolumny + wiersze) | `#f06292` |
| `liczba` | skalar (np. próg policzony z histogramu) | `#90a4ae` |
| `mesh` | (później) powierzchnia trójkątów | `#4db6ac` |
| `transformacja` | (później) macierz / pole deformacji | `#c0ca33` |

Reguły przejęte z praSzczur: łączenie tylko przy identycznym `kind`, `multi` dla wejść wielokrotnych, wykrywanie cykli, `id` typu w formacie `domena/nazwa`, stage `dane / przetwarzanie / wynik`.

**Node'y stanowe (nowość):** ręczna edycja pędzlem i markupy stawiane w viewporcie to node'y, które **przechowują własny stan** (pociągnięcia pędzla jako rzadka maska-delta względem wejścia, listę punktów). Narzędzie w viewporcie edytuje stan **aktywnego** node'a. Gdy wejście się zmieni, delta nakłada się ponownie, a node pokazuje ostrzeżenie. Ręczne edycje pozostają w ten sposób częścią odtwarzalnego grafu.

**Układ współrzędnych:** wewnętrznie wszystko w mm w **LPS** (jak DICOM), a każdy wolumen ma macierz IJK→LPS. Pomiary, crosshair i fuzja liczą się w świecie, nie w indeksach.

---

## 5. Node'y w MVP

Minimum domeny „Wolumen” (bez niego segmentacja nie ma wejścia):
- `wolumen/seria`: źródło z biblioteki workspace'u
- `wolumen/przytnij` (ROI), `wolumen/resampluj`, `wolumen/wygladz` (Gauss / mediana)

**Segmentacja:**
- `segmentacja/prog`: próg min–max (z histogramem i podglądem na żywo)
- `segmentacja/otsu`: próg automatyczny (wyjście `segment` + `liczba`)
- `segmentacja/rozrost`: region growing od punktów (wejście `punkty` jako seedy)
- `segmentacja/edycja`: stanowa (pędzel / gumka / wypełnij w viewporcie)
- `segmentacja/logika`: suma / część wspólna / różnica / XOR
- `segmentacja/morfologia`: dylatacja / erozja / otwarcie / zamknięcie / wypełnianie dziur
- `segmentacja/wyspy`: zostaw największą / usuń mniejsze niż N mm³ / wybierz klikiem
- `segmentacja/zloz`: kilka `segment` → `segmentacja` (nazwy, kolory)
- `segmentacja/rozloz`: `segmentacja` → wybrany `segment`
- `segmentacja/import`: DICOM-SEG / NIfTI labelmap z biblioteki

**Pomiary i statystyki:**
- `pomiary/markupy`: stanowy (punkt, linia = odległość, kąt, ROI-pudełko) → `punkty`
- `pomiary/statystyki_segmentu`: objętość [mm³/ml], powierzchnia, liczba woksli, min/max/średnia/SD/mediana intensywności → `tabela`
- `pomiary/histogram`: wolumen (+ opcjonalny segment) → `tabela` + wykres Plotly w node'ie
- `pomiary/profil`: profil intensywności wzdłuż linii
- `pomiary/eksport`: `tabela` → CSV

**Wyjścia / wyświetlanie:** każdy node z wyjściem ma przełącznik „pokaż w viewporcie” (oko). Segmentacje są renderowane w 3D jako labelmap; szybki mesh do wyświetlenia generuje sidecar wewnętrznie, bez osobnego node'a.

**Później (już przewidziane w architekturze):** domena Mesh (maska → mesh, wygładzanie, decymacja, eksport STL/OBJ, import STL), pełne filtry SimpleITK, transformacje i rejestracja, fuzja PET/CT, AI segmentacja (TotalSegmentator/MONAI jako opcjonalny pakiet, job z GPU/MPS), 4D, eksport DICOM-SEG/RTSTRUCT.

---

## 6. UI

Wygląd 1:1 z praSzczur (`docs/design/ui-tokens.md`), ale zdefiniowany w zmiennych CSS w `app/src/lib/ui/tokens.css`, nie wpisany na sztywno w komponentach.

**Zakładki:**
- **Dane**: biblioteka serii workspace'u (pacjent → badanie → seria, miniatury), import folderu/pliku (DnD + dialog), postęp importu, przeglądarka tagów DICOM, info o geometrii.
- **Scena**: split w stylu Blendera:
  - górna część: układy viewportów (1×1, 1+3, 2×2: 3D + osiowy/strzałkowy/czołowy), crosshair zsynchronizowany, W/L myszką, presety okien i transfer function, pasek narzędzi viewportu (nawigacja, pędzel, markupy) aktywny zależnie od zaznaczonego node'a;
  - dolna część: edytor Node Graph (pan/zoom, paleta pogrupowana domenami, miniatury plastrów w node'ach, pasek postępu na node'ach z jobem, ikonka (i) prowadząca do Dokumentacji), wiele grafów per workspace;
  - panel boczny: parametry zaznaczonego node'a, warstwy/sceny (co jest widoczne, kolor, przezroczystość), tabela wyników.
  - podziały przeciągane, rozmiary zapamiętywane przez `wsSet`.
- **Tablica, Notatki (+ FloatingNotePad), Dokumentacja**: port z praSzczur, plus „zrzut viewportu → Tablica”.
- **Ustawienia**: workspace'y (nowy/otwórz/import/eksport/zmień nazwę/usuń), grafy, anonimizacja, budżet GPU/RAM, czułość zoomu, colormapy, skróty.
- **ShortcutsModal**: globalny (np. `?`).

**Stan:** wszystko, co ma przetrwać restart i różnić się między workspace'ami, idzie przez `wsGet/wsSet`, a ustawienia globalne przez `getSetting/setSetting` (te same reguły co w praSzczur `CLAUDE.md`).

**Higiena kodu:** `NodeGraphTab.svelte` w praSzczur ma 4,9 tys. linii. W praTRD edytor jest od początku podzielony: `graph/canvas` (pan/zoom/rysowanie), `graph/interaction` (drag, łączenie, zaznaczanie, kopiuj-wklej przez zdarzenia DOM `copy/paste`), `graph/node-ui` (renderer z schematu), `graph/store`.

---

## 7. Struktura repo

```
praTRD/
├── CLAUDE.md · README.md · CHANGELOG.md · VERSION
├── dev.sh · build.sh                 # jak w praSzczur
├── pyproject.toml · uv.lock          # Python 3.13, przypięty lokalnie i w CI
├── .github/workflows/
│   ├── ci.yml                        # push/PR: ruff, pytest, svelte-check, vitest
│   └── release.yml                   # tag v*.*.* → macOS/Win/Linux (z praSzczur)
├── app/
│   ├── src/lib/
│   │   ├── core/      api.ts, workspace.svelte.ts, appSettings.svelte.ts, jobs.svelte.ts (WS)
│   │   ├── ui/        tokens.css, wspólne komponenty (Modal, Slider, Split, Icon…)
│   │   ├── viewport/  engine.ts (interfejs), vtk/ (implementacja), tools/ (pędzel, markupy)
│   │   ├── graph/     store, canvas, interaction, node-ui, palette
│   │   └── tabs/      dane/, scena/, tablica/, notatki/, dokumentacja/, ustawienia/
│   ├── src-tauri/     lib.rs (sidecar na dynamicznym porcie), build.rs (PRATRD_ROOT)
│   └── sidecar/       main.py (cienki entrypoint) + sidecar.spec
├── src/pratrd/                       # pakiet Python
│   ├── api/           routery: workspaces, settings, series, volumes, graphs, jobs, docs, boards, notes
│   ├── io/            dicom.py, anonymize.py, nifti.py, seg.py
│   ├── store/         zarr_store.py (piramida, kafle), geometry.py (IJK↔LPS)
│   ├── graph/         types.py, registry.py, evaluator.py, cache.py
│   ├── jobs/          kolejka, postęp, anulowanie
│   └── nodes/         wolumen/, segmentacja/, pomiary/
├── tests/                            # pytest na syntetycznych wolumenach (kula, sześcian)
├── docs/
├── source/                           # dane testowe użytkowniczki (gitignored)
└── notes/
```

**Główne zależności Python:** fastapi, uvicorn, pydicom (+ pylibjpeg, pylibjpeg-libjpeg, pylibjpeg-openjpeg dla skompresowanych transfer syntaxów), SimpleITK, numpy, zarr, numcodecs, scikit-image, scipy, nibabel, highdicom, pyinstaller. Bez VTK-python (ok. 100 MB, niepotrzebne, bo mesh do wyświetlania liczy skimage).

**Front:** @kitware/vtk.js, plotly.js-dist-min, konva, marked, @fontsource/jetbrains-mono, vitest.

---

## 8. Etapy

Każdy etap kończy się działającą aplikacją, zielonym CI i wpisem w `CHANGELOG.md`.

| Etap | Zakres | Kryterium „gotowe” |
|---|---|---|
| **E0 Fundament** ✅ | scaffold Tauri + SvelteKit + sidecar (port praSzczur), tokens.css, boot screen, `dev.sh`/`build.sh`, `ci.yml` + `release.yml`, workspace'y + ustawienia globalne, menu Workspace, PyInstaller **z całym stosem medycznym** (SimpleITK, pydicom, zarr) | `.app`/`.exe`/`.AppImage` z CI uruchamia się i sidecar odpowiada na każdym systemie |
| **E1 Dane** ✅ | skan folderu → grupowanie serii, biblioteka, tagi, anonimizacja, konwersja do zarr z piramidą (job + postęp + anulowanie), NIfTI/NRRD/DICOM-SEG import | duża seria z `source/` importuje się z paskiem postępu i nie zapycha RAM-u |
| **E2 Viewport** ✅ | `ViewportEngine` + vtk.js: MPR ×3 + 3D volume rendering, LOD, W/L, presety, crosshair, układy | płynna nawigacja (≥ 30 fps) na dużej serii |
| **E3 Node Graph** ✅ | edytor (port + podział), rejestr typów z Pythona, ewaluator, cache, podgląd/pełna rozdzielczość, joby na node'ach, wiele grafów, „pokaż w viewporcie”, node'y `wolumen/*` | graf seria → wygładź → widok działa na żywo |
| **E4 Segmentacja** ✅ | node'y z §5, narzędzia w viewporcie (pędzel, seedy), renderowanie labelmap 2D/3D | segmentacja kości progiem + wyspy + ręczna poprawka, zapis i odtworzenie po restarcie |
| **E5 Pomiary** ✅ | markupy, statystyki, histogram, profil, eksport CSV, panel tabeli | objętość segmentu zgadza się z wartością ze Slicera (±1%) na tych samych danych |
| **E6 Zakładki z praSzczur** | Dokumentacja (+ opisy node'ów z rejestru), Notatki + FloatingNotePad, Tablica + zrzut viewportu, ShortcutsModal | wszystkie działają per workspace / globalnie jak w praSzczur |
| **E7 Release 0.1.0** | testy wydajności na dużych danych, poprawki, tag `v0.1.0` | release z 3 instalatorami na GitHubie |

Po 0.1: domena Mesh → filtry SimpleITK → AI segmentacja (opcjonalny dodatek) → rejestracja i fuzja.

---

## 9. Ryzyka i sposób ich kontroli

| Ryzyko | Kontrola |
|---|---|
| PyInstaller + SimpleITK/pylibjpeg na Windows/Linux | sprawdzone już w E0, zanim powstanie funkcjonalność; `--onedir` zamiast onefile (szybszy start) |
| Za duży wolumen dla GPU/RAM | piramida + budżety w ustawieniach + ROI; testy na dużej serii w E1/E2 |
| Transfer sidecar → webview | binarne odpowiedzi, kafle, LOD; w razie potrzeby custom protocol Tauri |
| Słaby WebGL na Linuksie | wspierany, nie referencyjny; fallback na niższy level |
| Nieodtwarzalne edycje ręczne | node'y stanowe z deltą + ostrzeżenie po zmianie wejścia |
| Rozrost monolitów jak `NodeGraphTab.svelte` | podział modułów od startu, limit ok. 800 linii na komponent |
| Wypalenie (lekcja z praHand3D) | małe etapy, każdy daje działającą appkę; nie piszemy własnego silnika |
