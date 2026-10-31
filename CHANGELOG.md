# Changelog praTRD

Format: [Keep a Changelog](https://keepachangelog.com/), wersje: [SemVer](https://semver.org/).

## [Unreleased] — Scena: warstwy, Dane: foldery

- **Warstwy sceny** zamiast wyboru wolumenu w prawym panelu: oczko na karcie dodaje/usuwa warstwę; w panelu kolejność (przeciąganie ⋮⋮), ukrywanie, aktywna warstwa (klik) i rola (tło / nakładka / powierzchnia). Segmentację można nałożyć na dowolny wolumen z grafu; kilka meshy naraz.
- Na scenie jest tylko to, co włączono w grafie (pusta scena = podpowiedź). Karty warstw mają akcent na nagłówku, aktywna — pełną ramkę.
- Przełączanie oczka nie przesuwa przekrojów: kursor jest wspólny dla całej sceny (środek tylko, gdy punkt wypada poza nowy wolumen).
- Poprawki: `build.sh` instaluje w /Applications; **F w 3D** kadruje segment/mesh (też mały); presety 3D (Naczynia/Kości/Skóra) zawsze dostępne (poza HU rozciągane na zakres wolumenu); nowy node z wynikiem od razu ma oczko; warstwy — aktywna to tylko pierścień na kropce, na karcie cienka ramka zaznaczenia; pasek node'ów stały, zmiana szerokości przeciągnięciem krawędzi; suwaki krycia z podpisem i %.
- **Dane: foldery** (per workspace) — lista folderów z licznikami, przeciąganie serii na folder, import trafia do otwartego folderu; usunięcie folderu nie usuwa danych.

## Poprawka — zakładka Ustawienia

- Zakładka Ustawienia padała („Internal Error”, Svelte `each_key_duplicate`): rozmiary cache były liczone przesunięciem bitowym (`20 << 30` w JS = 0, `50 << 30` < 0), więc dwa przyciski miały klucz 0. Teraz mnożenie; „20 GB” zapisywałoby budżet 0, a 5 GB — 1 GB.
- Sidecar: budżet cache brakujący, błędny albo < 1 GB → domyślne 20 GB (nigdy nie czyści całego cache po każdym przeliczeniu). Test.

## [Unreleased] — E9 Filtry SimpleITK

- **Nowa domena „Filtry (SimpleITK)”** — 9 node'ów, wszystkie parametry w mm:
  - *Odszumianie* — dyfuzja anizotropowa krzywiznowa albo gradientowa (Perona–Malik), krok czasu z odstępu wokseli;
  - *Krawędzie* — moduł gradientu albo LoG (σ w mm);
  - *Naczyniowość* — wieloskalowy Frangi (rurki / płaszczyzny / kule), znormalizowany kontrastem w jednostkach obrazu → 0…1; próg 0,3 + Wyspy + Mesh daje drzewo naczyń z CTA;
  - *Wyostrz* (maska nieostra), *Morfologia szarości* (dylatacja, erozja, otwarcie, zamknięcie, top-hat jasne/ciemne, kula w mm);
  - *Arytmetyka* dwóch wolumenów (B próbkowany na siatkę A w świecie), *Maskuj wolumen* segmentem, *Mapa odległości* (mm, ze znakiem), *Korekcja pola N4* (MR).
- Filtry lokalne liczone **warstwami z marginesem** (wynik zgodny z całym wolumenem — testy), postęp i anulowanie między warstwami; filtry globalne (dyfuzja, N4, odległość) z postępem i przerwaniem przez obserwatora ITK.
- Mapy cech (gradient, naczyniowość, odległość) jako float32 z własnym oknem i bez modalności (bez presetów CT w HU).
- **Próg na mapach 0…1:** krok przeciągania na histogramie zależy od zakresu danych (1 HU na CT, 0,001 na naczyniowości), pola liczbowe przyjmują ułamki.
- **Widok node'a:** gdy wynik ma zupełnie inny zakres niż pokazywane wcześniej wejście (CT pod mapą 0…1), okno i preset 3D ustawiają się od nowa.
- **Błąd naprawiony przy okazji:** widok tablicy na tymczasowy obraz SimpleITK (`GetArrayViewFromImage(f(img))`) mógł czytać zwolnioną pamięć — obraz trzymany w zmiennej, dopóki widok żyje.
- Pomiary w `docs/03-wydajnosc.md`; smoke test zamrożonego sidecara: naczyniowość, dyfuzja, N4, mapa odległości. Testy: `tests/test_filtry.py` (14).

## [Unreleased] — E8 Mesh

- **Nowe gniazdo `mesh`** (powierzchnia trójkątów w świecie LPS mm) i domena **Mesh** w palecie:
  - *Mesh z segmentu* — marching cubes po wygładzeniu maski Gaussem (σ w mm, domyślnie 0,3), warstwami po 64 przekroje (stała pamięć), mesh zamknięty i zorientowany na zewnątrz;
  - *Wygładź mesh* — Taubin (bez kurczenia) albo Laplace;
  - *Decymacja* — zwijanie krawędzi z błędem kwadrykowym (`fast-simplification`), odsetek trójkątów w %;
  - *Plik mesha* — STL (ASCII/binarny), OBJ, PLY; układ LPS/RAS z nagłówka (jak Slicer) albo ręcznie; opcjonalne tło;
  - *Mesh → segment* — wnętrze zamkniętego mesha na siatce wolumenu (parzystość promieni wzdłuż k, tylko pudełko mesha);
  - *Statystyki mesha* — trójkąty, wierzchołki, powierzchnia, objętość (dywergencja), zamknięcie, wymiary.
- **Widoki:** mesh w 3D (vtk.js, Phong, krycie w panelu, tło jako „duch”), w 2D kontur przekroju w kolorze mesha; markupy stawiane na powierzchni mesha; zrzut na Tablicę zawiera kontur.
- **Karta node'a:** miniatura (widok z przodu, renderowana w sidecarze), ml / cm² / liczba △, ostrzeżenie dla otwartego mesha, **eksport STL / OBJ / PLY** (systemowe „Zapisz jako”, LPS).
- **Import STL/OBJ/PLY** w zakładce Dane (przycisk *Pliki…* i upuszczenie na okno) oraz przyciskiem w node'zie — biblioteka meshy workspace'u (`meshes/`), ten sam plik nie dubluje się.
- Sidecar: `/workspaces/{wid}/meshes` (lista, import, zmiana nazwy, usuwanie, `/data` binarnie, `thumb.png`, `export`); meshe w cache grafu (manifest, przycinanie budżetu, odtworzenie po restarcie); kopia LOD ≤ 1,5 mln △ dla widoków.
- Wyniki pomiarów w `docs/03-wydajnosc.md` (mesh kości 7 mln △ w 4,3 s, 60 fps z meshem w widokach).
- Smoke test zamrożonego sidecara: mesh z segmentu, decymacja, wokselizacja, eksport STL.
- Testy: `tests/test_mesh.py` (17), `viewport/meshcut.test.ts`.

## [0.1.0] — 2026-10-22

Pierwsze wydanie: dane (DICOM, DICOM-SEG, NIfTI, NRRD, MHA, anonimizacja), Scena (3 przekroje + 3D,
wspólny kursor), graf node'ów (wolumen, segmentacja, pomiary), narzędzia w widokach 2D i 3D
(ziarna, pędzel, gumka, nożyce, markupy), tabele z CSV, Tablica, Notatki, Dokumentacja, skróty.
Szczegóły etapów E0–E6 poniżej.

### E7 — wydajność na dużych danych
- `scripts/bench_large.py` (seria DICOM 512²×2000, NIfTI 1024²×1000) + wyniki w `docs/03-wydajnosc.md`.
- Pełna rozdzielczość na serii 1 GB: **15 s / 7,9 GB → 8,3 s / 5,5 GB**; Próg 5,5 → 2,0 s; region growing 4,7 → 1,25 s.
  - spis etykiet segmentu z histogramu zapisu (koniec 4 GB kopii w `bincount`), maski 0/1 przez `count_nonzero`;
  - Próg warstwami do wyniku, maska bool jako widok uint8; Wyspy bez drugiego obrazu etykiet;
  - wynik node'a od razu w pamięci podręcznej tablic (następny node nie dekoduje go z dysku).
- Interfejs na wolumenie 2 GB: pierwszy obraz 3D 0,38 s, przewijanie i obrót 3D p50 16 / p95 18 ms.
- `.gitignore`: `boards/` i `notes/` (mogą zawierać zrzuty z danych pacjenta).
- README: funkcje i instalacja niepodpisanych instalatorów (macOS `xattr`, Windows SmartScreen).
- Wersja 0.1.0 (Python, front, Tauri, Cargo, lockfile'y).

## [Unreleased] — E6 Zakładki z praSzczur

- **Tablica** (Konva, ładowana leniwie): tekst, kształty, pędzel, obrazy (przeciągnij / wklej / plik), warstwy ↑↓, cofanie 100 kroków, eksport całej tablicy do PNG, wiele tablic. Globalna; workspace pamięta ostatnią.
- **Zrzut viewportu na Tablicę:** ikona aparatu w rogu widoku 2D (przekrój + nakładka + markupy) i 3D (render + markupy); obraz z podpisem („Osiowy 224/341 · seria”) ląduje na ostatniej tablicy — na żywo, jeśli jest otwarta; powiadomienie „Dodano do tablicy ›” przenosi do niej.
- **Notatki:** lista z wyszukiwarką (strzałki + Enter), edytor z autozapisem, tytuł z pierwszej linii; **pływający notatnik** z przypiętą notatką nad całą aplikacją (ikona → podgląd → edycja, przeciągany, pozycja zapamiętana). **⌘/Ctrl+klik** na wartości (kursor, komórka tabeli, markup) dopisuje ją do notatki; zwykły klik kopiuje.
- **Dokumentacja:** poradnik dla każdej zakładki + „Pierwsze kroki”, własne strony (kolejność przeciąganiem), node'y z rejestru — porty i parametry rysowane ze schematu, opis w Markdown edytowalny; ten sam opis pod **(i)** na karcie node'a, a klik w (i) otwiera jego sekcję.
- **Okno skrótów** dla całej aplikacji (klawisz **?**, przycisk na Tablicy) — Scena, graf, Tablica, ogólne.
- Powiadomienia (toasty), nawigacja między zakładkami (`core/nav.svelte.ts`).
- Sidecar: `/notes`, `/boards` (+ zasoby obrazów: surowe bajty albo ścieżka z upuszczenia), `/app_docs`, `/export/png`; testy.
- Dev: `VITE_PRATRD_PORT` — port sidecara w zwykłej przeglądarce, gdy 7433 zajmuje inna lokalna aplikacja.

## Nożyce w Edycji pędzlem (po E5)

- **Nożyce** (jak „Scissors” w Slicerze) w node'zie Edycja: kształt lasso / prostokąt / elipsa; operacja: usuń wnętrze, wypełnij wnętrze, zostaw tylko wnętrze; głębokość w 2D: cały wolumen albo tylko bieżący przekrój; w 3D cięcie wzdłuż kierunku patrzenia (stożek z perspektywą albo graniastosłup w orto), Shift+przeciągnięcie dalej obraca.
- Cięcie zapisane jak pociągnięcie: macierz rzutu + wielokąt (mm / tangens kąta widzenia) — odtwarzane przy każdej zmianie wejścia; cofanie Cmd+Z / ↶ w karcie.
- Natychmiastowy podgląd: 2D w shaderze (maska edycji na siatce wyniku), 3D na danych nakładki w miejscu (84 ms na 244×243×341); wynik z sidecara identyczny z podglądem.
- Sidecar: widok równoległy do osi → maska 2D nakładana na zakres warstw (~0,03 s; cała głębokość 512²×621: 0,26 s), ogólny przypadek z ograniczeniem do obszaru przez odwróconą homografię warstwy (perspektywa: 0,54 s).

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
