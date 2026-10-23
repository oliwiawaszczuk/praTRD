# CLAUDE.md

## Projekt

**praTRD** — desktopowa aplikacja do pracy z danymi DICOM w 3D, z pipeline'ami jako **graf node'ów**.
Łączy praSzczur (workspace'y, ustawienia, styl UI, Node Graph), praHand3D (inspiracja) i 3D Slicer (funkcje).
Plan i etapy: `docs/02-plan.md` (zatwierdzony). Decyzje: `docs/01-qa.md`. Postęp: `CHANGELOG.md`.

**Stan: 0.1.0 gotowe (E0–E7) + E8 Mesh + E9 Filtry. Dalej wg planu: AI segmentacja → rejestracja i fuzja.**

## Zasady pracy

- **Git tylko do odczytu, zero GitHuba** (żadnych commitów, pushy, `gh`). Na koniec etapu zgłaszam, co jest gotowe do commita.
- **Kod zoptymalizowany od pierwszej linii**: ciężkie dane tylko w sidecarze, binarny transfer, kafle/piramida, operacje wektoryzowane, zero kopii buforów bez potrzeby, memoizacja ewaluacji grafu.
- **UX: obrazkowo, mniej tekstu.** Ikony, mini-diagramy, podglądy i gesty bezpośrednio w widoku
  (uchwyty, gizmo, przeciąganie na histogramie) zamiast akapitów; objaśnienia → tooltip. Każde
  ładowanie/liczenie widoczne (`ProgressRing`, `LoadingBar`, animacje kart).
- Komentarze i nazwy w kodzie: EN. Dokumentacja i UI: PL. Ikony: inline SVG (`Icon.svelte`), bez emoji.
- Dane medyczne (`source/`, `*.dcm`, `*.nii*`, `*.nrrd`) nigdy do gita.

## Uruchamianie

```bash
./dev.sh                 # Tauri dev + hot reload; sidecar przez `uv run python -m pratrd`, dane w ./workspaces
./build.sh               # szybki build .app (sidecar przez uv z tego projektu)
./build.sh --standalone  # jak release: zamrożony sidecar w .app, dane w ~/Library/Application Support/com.praoliwia.praTRD
./scripts/build-sidecar.sh   # PyInstaller + smoke test binarki (/diagnostics + prawdziwy import przez pulę)

uv run pytest -q && uv run ruff check src tests scripts       # Python
cd app && pnpm check && pnpm test                             # front
cd app/src-tauri && cargo clippy -- -D warnings               # Rust (też z --features pyinstaller-sidecar)
```

## Architektura (skrót)

```
app/src-tauri/   Rust: wybiera wolny port → spawn sidecara (env PRATRD_ROOT/PORT/PARENT_PID),
                 komenda `sidecar_port`, menu Workspace, close/Cmd+Q → event `close-requested`
                 → front flushuje zapisy → `window.destroy()` → Exit → kill sidecara.
app/src/lib/
  core/          api.ts (port z Tauri, getJson/sendJson), workspace.svelte.ts (wsGet/wsSet),
                 appSettings.svelte.ts (getSetting/setSetting), persisted.ts (debounce+flush),
                 tauri.ts (most do Tauri, działa też w zwykłej przeglądarce), workspaceActions.ts
  ui/            tokens.css (JEDYNE miejsce z kolorami), Icon, DialogHost + dialogs.svelte.ts, WorkspaceChip
  tabs/          jedna zakładka = jeden folder; Placeholder dla przyszłych etapów
app/sidecar/     main.py (entry PyInstaller) + sidecar.spec (--onedir, collect_all stosu medycznego)
src/pratrd/      pakiet Python: config, jsonio (atomowy zapis), workspaces (rejestr + layout), watchdog,
                 events (EventHub → WebSocket), jobs (JobManager: kolejki io/heavy, postęp, anulowanie),
  dicom/         frames (nagłówek → ramki), stack (sortowanie, fazy, geometria, dtype, ostrzeżenia),
                 scan (folder → Candidate), decode (w procesach puli), anonymize, tags
  meshes/        store (format katalogu .mesh, LRU MESHES, LOD, miniatura), io (STL/OBJ/PLY),
                 ops (marching cubes, Taubin, decymacja, wokselizacja), library (meshes/index.json)
  volumes/       geometry (IJK↔LPS), store (Zarr: writer, piramida, statystyki, read_slice),
                 decode_pool, files (NIfTI/NRRD), importer, library (index.json per workspace)
  api/           app (lifespan, state), system, workspaces, app_settings, volumes, jobs (+ /ws)
app/src/lib/core/events.svelte.ts   WebSocket: jobs, waitJob, onLibraryChanged
app/src/lib/core/library.svelte.ts  biblioteka wolumenów aktywnego workspace'u
app/src/lib/tabs/dane/              Dane, ImportDialog, importFlow, VolumeDetails, SlicePreview, TagBrowser
app/src/lib/viewport/               geometry.ts (IJK↔LPS, viewBasis: widok anatomiczny → osie indeksowe),
                                    slices.ts (fetch + LRU + SliceLoader), SliceRenderer.ts (WebGL2),
                                    SliceView.svelte, VolumeRenderer3D.ts (jedyne miejsce z vtk.js),
                                    View3D.svelte, volumeSource.ts, presets.ts, scene.svelte.ts, ViewportGrid
app/src/lib/tabs/scena/             Scena (siatka + miejsce na graf), ScenePanel
```

## Node Graph (KONWENCJE)

- Typy node'ów TYLKO w Pythonie: `src/pratrd/nodes/<domena>.py`, rejestrowane przez
  `register(NodeType(...))`, moduł dopisany w `nodes/__init__.py`. Front nie zna typów — renderuje
  porty i parametry ze schematu (`GET /node-types`).
- **Jak dodać node:** funkcja `run(ctx, inputs, params) -> {socket: value}`; wejścia to listy
  wartości per gniazdo (`VolumeValue` = uchwyt, `.array()` daje dane z LRU); wolumen wynikowy
  zawsze przez `ctx.volume_result(arr, geometry, info)`; długie operacje wołają `ctx.report(p)`
  (postęp + punkt anulowania); parametry fizyczne (mm), nie woksele; zmiana algorytmu → `version += 1`
  (stare wyniki z cache przestają pasować); test w `tests/test_graph.py`.
- Parametry są czyszczone (`clean_params`: domyślne, rzutowanie, przycięcie) — równe ustawienia
  muszą dawać ten sam klucz cache.
- Typy gniazd: identyczny `kind` albo brak połączenia (zero koercji) — sprawdzane w UI i w ewaluatorze.
- Id wolumenów: 12 hex = biblioteka (`store/`), 24 hex = wynik node'a (`cache/`) — wszystkie
  endpointy wokseli przyjmują oba.
- Front: `graph/store.svelte.ts` (dokument, mutacje, `commit()` = krok cofania — wołać na KOŃCU
  gestu, nie przy każdym ruchu), `graph/evaluation.svelte.ts` (sygnatura semantyczna bez pozycji →
  podgląd; bezczynność → pełna), geometria kart w `graph/layout.ts` (porty liczone, nie mierzone —
  zmiana wyglądu karty = zmiana stałych).
- Stan viewportów kluczowany „co jest wyświetlane” (`lib:<vid>` / `node:<gid>:<nid>`), kadr 2D
  w jednostkach świata — wynik node'a może zmienić geometrię bez skoku obrazu.

## Segmentacja (KONWENCJE)

- Segment = `VolumeValue(kind="segment")`, uint8 0/1; segmentacja = `kind="segmentacja"`, uint8
  0..N + `info.labels` [{id, name, color}]. Zawsze `info.ref` = wolumen tła (do nakładki).
  Zapis przez `ctx.volume_result(..., kind=...)` → piramida max + `info.voxels/ml/labelStats`.
- Pozycje (ziarna, pędzel) w świecie LPS mm, rozmiary w mm/mm³ — nigdy indeksy wokseli.
- Łączenie masek z różnych siatek → `_on_grid()` (nearest), nie zakładać równych kształtów.
- Front: `viewport/layers.ts` (OverlaySpec, SliceLayers), nakładka i próg w `SliceRenderer`,
  narzędzia w `graph/segTools.svelte.ts`, edytory kart w `graph/SegWidgets.svelte`.
- Parametr `strokes` węzła Edycja = kule pędzla ORAZ cięcia nożyc `{kind:"cut", mode, M, poly, z}`
  (M: świat → x,y,z,w; wielokąt w x/w, y/w) — ta sama definicja w `viewport/cuts.ts` i `_cut`.
- Pociągnięcia oczekujące = `layers.pending` (strokes z parametrów węzła, których wynik jeszcze
  nie zawiera — `info.strokes`); 2D rysuje je w shaderze (`viewport/strokes.ts` → tekstura edycji),
  3D zmienia dane nakładki w miejscu (`VolumeRenderer3D.paint/pick`).
- Wartości z cache na dysku odtwarza `value_from_json` — każdy nowy rodzaj wolumenu dopisać do
  `VOLUME_KINDS`, inaczej po restarcie dociera do węzłów jako None.
- Stan, który musi trafić do renderera (np. LUT), wgrywać w `draw()` gdy się zmienił — nie z
  efektu, który może się wykonać przed utworzeniem renderera.

## Mesh (KONWENCJE)

- Mesh = `MeshValue(kind="mesh")` — uchwyt do katalogu `<ref>.mesh/` (`verts.bin` f32, `normals.bin`
  f32, `cells.bin` u32 w układzie VTK `3,a,b,c`, `meta.json`); wierzchołki ZAWSZE świat LPS mm.
  12 hex = biblioteka (`meshes/`, import plików), 24 hex = wynik node'a (`cache/`).
- Wynik przez `ctx.mesh_result(verts, faces, info)` (statystyki: area, ml, closed, bounds dopisuje
  sam); bibliotekę przez `ctx.library_mesh(mid)`. `info.ref` = tło do wyświetlenia; zmiana samego
  `info` (np. tło) nie kopiuje plików — `info` żyje w manifeście cache.
- Orientacja: normalne na zewnątrz, objętość > 0 — po każdej operacji, która może odwrócić
  kolejność (marching cubes w [k,j,i], lewoskrętna macierz kierunków), `ops.orient_outwards`.
- Marching cubes warstwami (`ops._SLAB`) + spawanie płaszczyzn styku — nigdy cały bbox naraz.
- Do frontu idą pliki bez konwersji (`/meshes/{ref}/data`); > `DISPLAY_FACES` → kopia LOD w
  `<mesh>/lod` (raz). vtk.js tylko w `VolumeRenderer3D.setMeshes`; kontur 2D w `viewport/meshcut.ts`
  (afiniczne głębokość/ekran z `ViewProj`, głębokości wierzchołków cache'owane per orientacja).
- Plik: `meshes/io.py` (STL/OBJ/PLY), nagłówek `SPACE=LPS|RAS` przy zapisie i odczycie.

## Filtry (KONWENCJE)

- Filtr lokalny → `filtry.slabbed(ctx, arr, g, margin_k, fn, dtype, label)`: warstwy wzdłuż k z
  marginesem ≥ zasięg filtra (Gauss 4σ, Hessian 3σ, morfologia r × przejścia); test zgodności z
  całym wolumenem w `test_slabs_equal_whole_volume`. Duże bufory per woksel → `share < 1`.
- Filtr globalny (normalizacja po całym obrazie, np. dyfuzja anizotropowa, N4, odległość) — na
  całym wolumenie przez `run_filter(ctx, filt, ...)` (postęp ITK + `Abort()` przy anulowaniu).
- Wygładzanie zachowuje dtype wejścia (`_cast_like`); mapa cech = float32 + `_info(v, s, arr)`
  (własne okno z percentyli, `modality=""`).
- `sitk.GetArrayViewFromImage(x)` — `x` MUSI być w zmiennej do końca użycia widoku (widok nie
  trzyma obrazu; tymczasowy = śmieci w wyniku). Lekcja z E9.

## Pomiary (KONWENCJE)

- Wynik tabelaryczny = `DataValue("tabela", {title, columns:[{key,label,unit}], rows, chart})`
  przez `pomiary.table(...)`; `chart` = podpowiedź dla karty (`bars` / `histogram` / `line`).
  Front: `graph/tables.ts` (CSV, eksport), `TableChart`, `TableModal`, `tableView.svelte.ts`.
- Markupy = parametr `markups` node'a `pomiary/markupy` (świat LPS mm); niedokończone są odrzucane
  przez `clean_params`. Pomiar liczony w obu miejscach tak samo (`viewport/markups.ts` ↔
  `markup_measure`). Szkic/przeciągany markup w `viewport/markupDraft.svelte.ts` (wspólny dla
  wszystkich widoków), zapis do node'a dopiero na końcu gestu.
- Warstwy nad widokiem 2D dostają `ViewProj` (świat↔ekran, głębokość względem przekroju) — nie
  sięgają do wnętrza `SliceView`.

## Tablica / Notatki / Dokumentacja (KONWENCJE)

- Globalne (folder danych: `notes/`, `boards/`, `app_docs.json`), nie per workspace — jak w praSzczur.
- Wszystko, co trafia na tablicę spoza zakładki, idzie przez `addImageToBoard` (otwarta tablica
  dostaje obiekt na żywo przez `registerLiveBoard`, inaczej zapis w sidecarze) — nigdy nie
  nadpisywać `board.json` obok otwartego płótna.
- Kopiowanie wartości do notatki: `copyValue(text, event)` z `core/notePad.svelte.ts`.
- Opis node'a czytać przez `nodeDoc(typeId, fallback)` (nadpisania z Dokumentacji).
- Zakładka jest dzieckiem `.pane` (flex w wierszu) — jej korzeń musi mieć `flex: 1; min-width: 0`,
  inaczej ma szerokość treści (lekcja z E6: płótno Tablicy miało 0 px).
- Skróty klawiszowe zakładki działają tylko, gdy jest widoczna (`root.offsetParent`) — zakładki
  zostają zamontowane w tle. Nowy skrót → dopisać do `ui/ShortcutsModal.svelte`.
- Test w przeglądarce, gdy port 7433 jest zajęty: sidecar z `PRATRD_PORT=7533`, Vite z
  `VITE_PRATRD_PORT=7533`.

## Pamięć przy dużych wolumenach (lekcja z E7)

- Nigdy `np.bincount` / porównania na całym wolumenie naraz bez potrzeby: `bincount` kopiuje
  wejście do `intp` (8 B/woksel). Zliczać kawałkami (≤ 16 M wokseli) albo `count_nonzero`.
- Maski budować warstwami (`_slabs`) prosto do tablicy wynikowej; bool → uint8 przez `.view`.
- Obrazy etykiet SimpleITK (uint32) tylko oglądać `GetArrayViewFromImage` i zwalniać od razu.
- Zmiana w węźle ciężkim → `uv run python scripts/bench_large.py dicom` przed i po.

## Skrypty edytujące pliki (lekcja z E4)

- Każda podmiana tekstu w skrypcie MUSI sprawdzać, że coś znalazła (`assert old in s`) — po
  `ruff format` stare fragmenty nie pasują i zmiana po cichu przepada (testy wtedy kłamią).

## Viewporty (KONWENCJE)

- vtk.js importujemy WYŁĄCZNIE w `VolumeRenderer3D.ts`; reszta appki go nie zna.
- 2D: przekroje zawsze z sidecara przez `SliceLoader` (nigdy cały wolumen do 2D). Mapowanie
  ekran→teksel liczone dla poziomu FAKTYCZNIE wyświetlonego (`shown.req.level`), nie żądanego.
- Kursor = jeden punkt LPS w `scene` — przewijanie/klik zmieniają kursor, widoki go tylko czytają.
- Wszystkie widoki zostają zamontowane przy zmianie układu (ukrycie = CSS); ukryty widok nic
  nie pobiera ani nie rysuje (W/H = 0).
- Rysowanie na żądanie (jeden rAF na zmianę), nigdy pętla renderowania w tle.
- Svelte 5: efekt NIGDY nie może czytać stanu, który sam zapisuje (renderer w zmiennej lokalnej,
  `untrack(() => x++)`); liczniki globalne zmieniane z wnętrza efektów (np. `tracked()`) → `untrack`.
- **Real-time = priorytet nr 1.** Każdy gest na 3D (uchwyty, suwaki, gizmo) owijać w
  `renderer.beginInteraction()/endInteraction()` — vtk.js obniża rozdzielczość TYLKO gdy jego
  interaktor „animuje”; zmiany programowe przez `requestRender()` (raz na klatkę); obiekty vtk.js
  (np. płaszczyzny przycinania) aktualizować, nie tworzyć na nowo. Mierzyć: skrypt rAF w
  Playwright/WebKit @2x z ruchami myszy co 16 ms (p50/p95 ms na klatkę) — przed i po.
- Nakładki na 3D (gizmo, box przycinania) używają `VolumeRenderer3D.project/cameraBasis/onCamera`
  — nie importują vtk.js.
- Haki pomiarowe tylko w DEV: `window.__pratrd3d.benchmarkOrbit()`, `window.__pratrdShown`.
- Test produkcyjnego CSP: zwykły serwer + nagłówek CSP z `tauri.conf.json` ORAZ hashe skryptów
  inline (Tauri dopisuje je sam przy buildzie — bez tego SvelteKit nie wystartuje).

## Dane wolumenów (KONWENCJE — nie łamać)

- Tablice zawsze **[k, j, i]** (C-order); spacing/size/direction w kolejności **(i, j, k)** jak ITK;
  świat = **LPS mm**, `world = origin + D @ (spacing * ijk)`, origin = środek woksela (0,0,0).
- Workspace: `series/index.json` (lekkie wpisy), `series/<vid>/{tags.json,thumb.png}`,
  `store/<vid>.zarr/{0,1,…}` + atrybut grupy `pratrd` (levels, stats, dtype). Wolumen nigdy nie jest
  nadpisywany w miejscu (miniatura ma cache „immutable”) — zmiana = nowy vid.
- Zapis zawsze przez `VolumeWriter` (strumieniowo, `.partial` → rename); ciężka praca = job
  (`jobs.submit(..., lane="heavy")`) z `job.report()` w pętli (to też punkt anulowania).
- Dane binarne do frontu: surowe little-endian + nagłówek `X-Meta`, bez JSON-a i bez kompresji.
- CPU-bound w Pythonie z GIL-em → `decode_pool.ordered_map` (procesy), nie wątki. Funkcja dla
  puli musi być top-level i importowalna (spawn) — w zamrożonym buildzie sprawdza to smoke test.
- Testy geometrii na syntetycznych danych: `tests/synth.py` (`write_series`, `write_nifti`).

## Konwencje, które łatwo złamać

- **SvelteKit 3**: konfiguracja w `vite.config.js` (`sveltekit({...})`), NIE ma `svelte.config.js`.
  Importy przez subpath imports **`#lib/...` z pełnym rozszerzeniem** (`#lib/core/api.ts`,
  `#lib/core/workspace.svelte.ts`, `#lib/ui/Icon.svelte`). `$lib` nie istnieje.
- TypeScript przypięty do **6.x** (TS 7 nie ma JS API, którego używa SvelteKit).
- Stan UI per workspace → `wsGet/wsSet`; globalny → `getSetting/setSetting`; nigdy `localStorage`.
  `wsSet` z obiektem: przekazuj nową wartość (obiekty zawsze są zapisywane, prymitywy tylko przy zmianie).
- `window.prompt/confirm/alert` nie działają w webview → `promptText/confirmAction/showError/showInfo`.
- Zakładki montują się przy pierwszej wizycie i zostają zamontowane (ukryte) — ciężki stan (WebGL)
  nie może być odtwarzany przy każdym przełączeniu.
- Sidecar: endpointy sync działają w threadpoolu → każdy read-modify-write rejestru pod lockiem;
  ciężkie importy (SimpleITK, skimage…) leniwie, nigdy w ścieżce `/health`.
- Nowa biblioteka importowana leniwie w sidecarze → dopisz do `_DEPS` w `api/system.py` i, jeśli
  potrzeba, do `collect_all` w `sidecar.spec` — inaczej zamrożony build padnie dopiero u usera.
- Nie zapisuj niczego do wnętrza bundla `.app` (macOS App Management blokuje proces).
- Nie usuwaj domyślnego menu Edytuj (Cmd+C/V w polach tekstowych WKWebView).

## Dane testowe

Pierwsze uruchomienie świeżo zbudowanego sidecara na macOS trwa 10–15 s (skan nowych bibliotek
przez system), kolejne ~0,3 s — to nie regresja.

`source/sample IA/` — CTA głowy (Philips), 621 × 512×512, 0,39 × 0,39 × 0,9 mm, JPEG Lossless (SV1),
+ `annotation_002.stl` (mesh tętniaka, ASCII STL) + `Metadata.csv` (tabela badań, separator `;`).
