# Changelog praTRD

Format: [Keep a Changelog](https://keepachangelog.com/), wersje: [SemVer](https://semver.org/).

## [Unreleased] — E5 Pomiary

- **Node'y pomiarów** (`nodes/pomiary.py`): Markupy (punkt, linijka, kąt, ROI) → punkty + tabela; Statystyki segmentu (woksele, mm³, ml, powierzchnia, min/max/średnia/SD/mediana — dla segmentu albo każdej etykiety, intensywność z podłączonego wolumenu lub tła segmentu); Histogram (cały wolumen albo w masce); Profil (wartości wzdłuż linijki, interpolacja liniowa co ½ woksela).
- **Nowe wartości w grafie:** `tabela` i `punkty` (`DataValue`) — przeżywają cache na dysku jak wolumeny.
- **Markupy w widokach:** narzędzia w karcie node'a (ikony); linijka kliknięciami albo przeciągnięciem, kąt trzema kliknięciami, ROI przeciągnięciem prostokąta (głębokość uchwytami w drugim widoku); uchwyty przeciągane na żywo we wszystkich widokach (p50 17 / p95 22 ms @2x); w 3D rzut z etykietami, punkt/linijka/kąt stawiane na powierzchni. Najechanie na pozycję listy podświetla markup, klik przenosi kursor, dwuklik zmienia nazwę.
- **Tabele:** mini-wykres na karcie (słupki objętości w kolorach segmentów, histogram, profil), sekcja „Pomiary” w panelu bocznym, okno pełnej tabeli z eksportem CSV (UTF-8 BOM, `;`, przecinek dziesiętny).
- Pełna rozdzielczość po bezczynności liczy się też dla node'ów z tabelą (nie tylko wyświetlanego).
- **Kryterium etapu:** objętość = liczba wokseli × objętość woksela (jak „Volume” w Segment Statistics Slicera) — na danych testowych 2 122 203 woksele = 145,70 ml, zgodnie z node'em Próg co do woksela; test na fantomie (dokładnie) + powierzchnia kuli w ±4%.
- Smoke test zamrożonego sidecara liczy też statystyki (skimage) i profil (scipy).

## Poprawki po E4

- **Widok 3D nie resetuje kamery** przy przeliczeniu wyniku: kamera wraca do startu tylko dla pierwszego wolumenu albo zupełnie innego obszaru. Segment pokazany za Przytnij trzyma tło pełnej rozdzielczości (podgląd segmentu nie podmienia wolumenu 3D).
- **Płaszczyzny przekrojów w 3D** (jak w Slicerze): prostokąty osiowy/czołowy/strzałkowy w kolorach widoków + punkt kursora, przełącznik pod przyciskiem orto.
- **Pędzel i gumka w widoku 3D:** promień z piksela trafia w maskę (gumka) albo widoczną tkankę (pędzel); maska zmienia się na żywo (17/18–20 ms na klatkę @2x); start w pustym miejscu, Shift albo inny przycisk = zwykłe obracanie.
- **Gumka 2D bez „resztek”:** pociągnięcia oczekujące rysowane w shaderze jako maska edycji na siatce wokseli wyniku (to samo, co policzy sidecar), zamiast półprzezroczystych kółek; kanciasty podgląd nie podmienia pełnej maski w trakcie edycji; liczący się węzeł zachowuje ostatnie wyjścia (nakładka nie mruga).
- **Błąd cache:** segment/segmentacja wczytane z cache na dysku (po restarcie) trafiały do kolejnych węzłów jako puste wejście („Podłącz segment…”). Test regresji.
- **Stan wyświetlanego węzła:** błąd/brak wejścia pokazany jako ostrzeżenie zamiast wiecznego „Liczenie…”; bez wyniku widoki pokazują wejście węzła (w pełnej rozdzielczości), Region growing bez ziaren — pasek włącza narzędzie ziarna.

## [Unreleased] — E4 Segmentacja
### Added
- **Node'y segmentacji**: Próg, Otsu (+ wyjście z wartością progu), Region growing (ziarna
  klikane w widoku; metody: tolerancja — domyślna, bez znajomości HU; zakres; adaptacyjna),
  Edycja pędzlem (pędzel/gumka, pociągnięcia zapisane w node'zie jako kule w mm — nakładają się
  ponownie po zmianie wejścia), Logika (∪ ∩ − ⊕, dopasowanie siatek), Morfologia (dylatacja,
  erozja, otwarcie, zamknięcie, wypełnianie dziur; promień w mm), Wyspy (N największych /
  min. objętość mm³), Złóż / Rozłóż (segmenty ↔ mapa etykiet), Labelmapa (z biblioteki).
- **Import DICOM-SEG** (highdicom) jako mapa etykiet w bibliotece — siatka zgodna co do woksela z
  serią źródłową, nazwy segmentów z pliku.
- Maski w magazynie: `uint8`, piramida przez **maksimum** (cienkie naczynia nie znikają na
  zgrubnych poziomach), liczba wokseli i objętość (ml) per etykieta — widoczne na karcie node'a.
- **Nakładka 2D** (druga tekstura + LUT kolorów, wypełnienie + kontur 1 px w przestrzeni ekranu,
  własna macierz — maska może mieć inną rozdzielczość niż tło), **3D**: maska jako wolumen w kolorze,
  tło jako „duch”.
- **Próg na żywo**: przeciąganie progu na histogramie → widoki 2D kolorują woksele w zakresie
  bezpośrednio w shaderze (pełna rozdzielczość, bez czekania na backend).
- Karty: histogram z pasmem progu, przyciski narzędzi (ziarna, pędzel, gumka), promień pędzla
  (`[` `]`), cofnij ostatnie pociągnięcie; objętość ml + kolor segmentu; miniatury w kolorze.
- Panel Sceny: krycie nakładki i kontur. ⌘Z działa też poza edytorem grafu, Esc wyłącza narzędzie.

### Measured (@2x)
- przeciąganie progu: p50 17 ms / p95 29 ms; malowanie pędzlem: p50 17 ms / p95 19 ms
- po przeładowaniu aplikacji wyniki segmentacji wracają z cache w ~15–60 ms

### Fixed
- Pusta tabela kolorów nakładki (efekt mógł się wykonać przed utworzeniem renderera).
- Region growing: pusty wynik wyjaśnia przyczynę (wartość ziarna vs zakres).

## Płynność w czasie rzeczywistym
### Fixed
- **Przycinanie na żywo**: płaszczyzny tworzone raz i tylko przesuwane (zmiana ich zestawu
  przebudowywała shader vtk.js) + gesty działają w trybie animacji interaktora vtk.js
  (adaptacyjna rozdzielczość pod 60 fps, pełna jakość po puszczeniu). Przeciąganie uchwytu:
  p50 92 → 17 ms, p95 945 → 20 ms na klatkę (Retina @2x).
- To samo dla przeciągania gizma i suwaków w modalu; render programowy maks. raz na klatkę.

### Added
- Przełącznik perspektywa ↔ ortograficzny w widoku 3D (przycisk pod gizmem, klawisz 5 jak w Blenderze).
- Modal potwierdzenia usuwania node'ów (lista usuwanych; ⌘Z nadal cofa); przycisk „Usuń” czerwony.

### Measured (@2x, M-series): obracanie 3D zmaksymalizowane 17 ms/klatkę, przeciąganie kursora 2D
  17 ms z doczytywaniem przekrojów w 2 pozostałych widokach, uchwyt boxa 17 ms.

## Poprawki UX po E3
### Changed
- **Sidebar Sceny „obrazkowo”**: wolumen jako karta z miniaturą (lista miniatur), układy jako
  ikony mini-siatek, okno/poziom rysowane i przeciągane na histogramie wolumenu (+ chipy presetów),
  presety 3D jako kafelki z paskiem kolorów, kursor w kolorach osi; opisy → tooltipy.
  Budżet GPU i budżet cache grafu → Ustawienia → „Wydajność” (kafelki).
- Node „Przytnij”: zamiast 6 suwaków procentowych mini-diagram izometryczny + modal 3D.

### Added
- Suwak warstw w nagłówku każdego widoku 2D (jak w Slicerze); okno/poziom tylko w trakcie zmiany.
- Gizmo orientacji w widoku 3D (jak w Blenderze): klik w L/R/A/P/S/I = widok z tej strony,
  przeciąganie = obrót; kolory osi jak w Slicerze.
- **Modal przycinania 3D** (jak collider w Unity): 6 uchwytów na ścianach boxa, przycinanie
  wolumenu na żywo (płaszczyzny vtk.js), suwaki dwuuchwytowe per oś z wymiarami w mm.
- Pełny ekran grafu / widoków: Ctrl+Spacja nad obszarem, przyciski na pasku podziału i w pasku grafu.
- Ładowanie: globalny pasek pod zakładkami, pierścień postępu w 3D (środek → róg przy
  doczytywaniu), wskaźnik oczekiwania w widokach 2D, wirująca obwódka liczącego node'a,
  szkielet miniatury.
- Typ node'a może deklarować `widget` (własny edytor na karcie zamiast parametrów).

### Fixed
- Pętle efektów (renderer 3D, gizmo, licznik żądań w `tracked()` czytany wewnątrz efektów).

## E3 Node Graph
### Added
- **Silnik grafu w sidecarze** (`graph/`): typy node'ów w Pythonie jako jedyne źródło prawdy
  (`GET /node-types` → UI generowane ze schematu), ewaluacja tylko domknięcia celów, wykrywanie
  cykli, ścisłe typowanie gniazd, błąd blokuje tylko gałąź w dół, stany node'ów na żywo
  (WebSocket `graph-node`). Cache adresowany treścią (typ + wersja algorytmu + parametry +
  klucze wejść), trwały między sesjami (`cache/<klucz>.json|.zarr`), budżet dyskowy z LRU.
- **Podgląd / pełna rozdzielczość**: zmiana parametru → podgląd całego grafu (~0,2 s, poziom
  piramidy ≤ 16 M wokseli); po chwili bezczynności → pełna rozdzielczość wyświetlanego node'a w tle
  (przełącznik „auto” + przycisk). Nowe żądanie anuluje poprzednie.
- **Node'y domeny Wolumen**: Seria, Przytnij, Resampluj (izotropowo, liniowa/B-spline/NN),
  Wygładź (Gauss σ / mediana r) — parametry w mm, więc podgląd i pełna dają ten sam efekt.
- **Edytor grafu** w dolnym panelu Sceny: karty node'ów z parametrami, stanem, czasem, miniaturą
  wyniku i okiem wyświetlania; paleta (przeciąganie), wyszukiwarka (PPM / spacja), połączenia
  przeciąganiem (odpięcie z wejścia, upuszczenie w pustym miejscu → przefiltrowane menu +
  autopołączenie), zaznaczanie prostokątem / ⇧, grupowe przesuwanie, Delete, ⌘Z/⇧⌘Z (cofnij /
  ponów), ⌘D, ⌘C/⌘V, F (dopasuj), wiele grafów na workspace (nowy / zmiana nazwy / usuwanie).
- **Wynik node'a w viewportach**: oko → wszystkie widoki 2D/3D pokazują wynik; stan widoku
  (kursor, okno, preset 3D) kluczowany node'em, kadr w jednostkach świata — zmiana parametru
  podmienia obraz bez skoku; znacznik „Podgląd”.
- Granice błędów (`svelte:boundary`) dla zakładek, widoków i edytora — awaria jednego elementu nie
  wyłącza aplikacji.
- Smoke test zamrożonego sidecara liczy graf seria → mediana → resampling.

### Measured (CTA 621 × 512²)
- podgląd po zmianie σ: ~0,2 s od suwaka do obrazu; pełna rozdzielczość (Gauss, 163 M wokseli,
  z zapisem piramidy): ~3 s w tle.

### Fixed
- Zaznaczanie tekstu w WebKit (brak prefiksu `-webkit-user-select`).
- Zapis grafu przy zamknięciu/przeładowaniu strony w ciągu 300 ms od zmiany.
- Odczyt poziomu poprzedniego wolumenu w widokach 2D/3D przy przełączaniu (wyjątek renderowania).

## E2 Viewport
### Added
- **Zakładka Scena**: układy 2×2 (Slicer four-up), „3D + 3”, pojedynczy widok; dwuklik =
  maksymalizacja; dolny obszar na Node Graph (E3) z przeciąganym podziałem; panel boczny
  (wolumen, układ, okno/poziom + presety CT, preset 3D, budżet GPU, kursor w LPS).
- **Widoki 2D (osiowy / czołowy / strzałkowy)** — własny renderer WebGL2: przekrój wgrywany
  bez konwersji jako tekstura całkowitoliczbowa (R16I/R16UI/R32I/R8UI/R32F), interpolacja
  dwuliniowa i okno/poziom w shaderze. Orientacja radiologiczna z macierzy kierunków (także
  dla serii permutowanych/odwróconych), litery R/L/A/P/S/I, krzyż w kolorach Slicera,
  wspólny kursor LPS, kółko = warstwa, PPM = okno/poziom, ⌘/Ctrl+kółko lub pinch = zoom w punkt,
  środkowy / ⇧+przeciąganie = przesuwanie, odczyt wartości woksela pod myszą.
- **LOD 2D**: poziom piramidy dobierany do zoomu (teksel ≤ 1,5 px urządzenia); ładowanie
  „najnowsze wygrywa” (jedno żądanie w locie) + prefetch 4 warstw w kierunku przewijania.
- **Widok 3D (vtk.js)**: ray casting, progresywnie (zgrubny poziom natychmiast → największy
  poziom w budżecie GPU), 2 B/woksel na GPU, presety: CT naczynia / kości / skóra, MIP,
  ogólny (wg histogramu); kamera od przodu, głowa u góry.
- Sidecar: cache zdekodowanych chunków (512 MB, LRU) dla przekrojów; strumieniowanie całego
  poziomu `GET …/level/{L}` (Content-Length → jeden prealokowany bufor po stronie UI).

### Measured (CTA 621 × 512², WebKit/Apple GPU, Retina @2x)
- przekrój z sidecara: pierwszy w warstwie chunków 18 ms, kolejne 0,2–1,6 ms (było 12 ms każdy)
- przewijanie 2D w pełnej rozdzielczości: 90/90 kroków kółka wyświetlonych, klatka p50 16 ms / p95 19 ms
- 3D pełna rozdzielczość (163 M wokseli): 9,8 ms/klatkę w 2×2, 27,9 ms zmaksymalizowany
  (2660 × 1464 px urządzenia) — pomiar z wymuszoną synchronizacją GPU, najwyższa jakość
- pierwszy obraz 3D po 0,6 s; poziom 0 (326 MB) przesyłany w ~0,3 s

### Fixed
- WebSocket: nieodebrany wyjątek taska przy rozłączeniu klienta.

## E1 Dane
### Added
- **Import**: skan folderów/plików → grupowanie serii DICOM (SeriesInstanceUID + orientacja +
  wymiary), sortowanie po pozycji wzdłuż normalnej (nie InstanceNumber), rozbicie na fazy
  (powtarzające się pozycje), DICOM klasyczny i enhanced multi-frame, NIfTI (strumieniowo, RAS→LPS),
  NRRD/MHA (SimpleITK). Ostrzeżenia: nierówne odstępy / brakujące warstwy, pochylenie gantry,
  niekompletne fazy, RGB → luminancja, brak geometrii. Wykrywanie serii już zaimportowanych.
- **Magazyn wolumenów** (Zarr v3): chunki 64³ (głębokość adaptacyjna przy ogromnych przekrojach),
  Blosc zstd-1 + bitshuffle, piramida rozdzielczości dążąca do izotropii, histogram i percentyle,
  zapis do `*.partial` + atomowe przemianowanie, sprzątanie przerwanych importów przy starcie.
- **Dekodowanie w puli procesów** (spawn, maks. 6, wyłączana po 90 s bezczynności) — 7× szybciej
  niż w jednym procesie (dekoder JPEG trzyma GIL, wątki nic nie dają).
- **Zadania w tle**: kolejki `io`/`heavy`, postęp (≤10 zdarzeń/s), anulowanie, WebSocket `/ws`
  ze snapshotem przy (ponownym) połączeniu; pływający panel zadań w UI.
- **Anonimizacja** (PS3.15 Basic, opcja „Retain Patient Characteristics”): usuwa dane osobowe,
  daty, instytucje, wszystkie UID-y instancji i tagi prywatne; stały pseudonim ANON-xxxx (sól per
  instalacja); bez zapisu ścieżki źródła. Domyślne ustawienie globalne + przełącznik przy imporcie.
- **Zakładka Dane**: biblioteka z miniaturami, import przyciskami i przeciągnięciem plików na okno,
  okno wyboru serii, szczegóły (informacje, ostrzeżenia, zmiana nazwy, usuwanie), przeglądarka
  tagów z wyszukiwaniem, podgląd przekrojów (3 osie, kółko = warstwa, przeciąganie = okno/poziom,
  presety CT, automatyczny wybór poziomu piramidy, cache LRU przekrojów).
- API: `/workspaces/{wid}/scan|import|volumes[/{vid}[/meta|tags|thumb.png|slice]]`, `/jobs`, `/ws`.
- Smoke test zamrożonego sidecara wykonuje prawdziwy import przez HTTP (ścieżka puli procesów).

### Measured (CTA głowy 621 × 512², JPEG Lossless, M-series)
- skan nagłówków 0,16 s · import 1,4 s · 326 MB → 151 MB na dysku · szczyt RAM importu ~270 MB
  (niezależny od liczby warstw) · przekrój osiowy z dysku ~12 ms.

### Changed
- Usunięty GZip z sidecara (na loopbacku tylko koszt CPU, szczególnie dla danych binarnych).

## [0.0.1] - 2026-10-22 — E0 Fundament
### Added
- Szkielet aplikacji: Tauri v2 + SvelteKit 3 / Svelte 5 + sidecar Python 3.13 (FastAPI, uv).
- Sidecar `pratrd`: `/health`, `/diagnostics` (wersje bibliotek + dostępność dekoderów DICOM
  JPEG / JPEG-LS / JPEG2000 / RLE), workspace'y (CRUD, aktywacja, ustawienia per workspace,
  eksport/import bez `cache/`), ustawienia globalne. Atomowy zapis JSON, blokada rejestru.
- Front: ekran startowy, pasek zakładek (Dane, Scena, Tablica, Notatki, Dokumentacja, Ustawienia)
  montowanych leniwie i trzymanych w pamięci, przełącznik workspace'ów, zakładka Ustawienia
  (workspace'y + diagnostyka), modale Promise (`promptText`/`confirmAction`/`showError`).
- `wsGet/wsSet` + `getSetting/setSetting` z debounced zapisem i flush przy zamknięciu okna/Cmd+Q.
- Design tokens praSzczur w `tokens.css`, JetBrains Mono, ikona aplikacji.
- Menu natywne „Workspace” (nowy / przełącz / import / eksport).
- `dev.sh`, `build.sh` (`--standalone` = zamrożony sidecar w `.app`), `scripts/build-sidecar.sh`
  + smoke test binarki, workflowy `ci.yml` i `release.yml` (macOS / Windows / Linux).

### Changed (względem praSzczur)
- Port sidecara wybierany dynamicznie przy każdym starcie (komenda Tauri `sidecar_port`) zamiast
  stałego portu i zabijania procesu, który go zajmuje.
- Sidecar sam się wyłącza, gdy proces aplikacji zniknie (`PRATRD_PARENT_PID` watchdog).
- PyInstaller `--onedir` zamiast onefile (start ~0,2–1,3 s), konfiguracja zasobów przez
  nakładkę `tauri.standalone.conf.json` zamiast edycji `tauri.conf.json` w CI.
- Brak bezwarunkowego `chmod` w bundlu (wieszał aplikację uruchamianą z Findera).
