# praTRD: plan etapu E10 — Symulacje przepływu krwi

Status: **PROJEKT, do zatwierdzenia** (2026-10-24). Po zatwierdzeniu: wpis w `02-plan.md` §8
(E10 przed AI segmentacją) i decyzje w `01-qa.md`.

## 0. Decyzje (Q&A 2026-10-24)

| # | Pytanie | Odpowiedź | Konsekwencja |
|---|---|---|---|
| 16 | Cel wyników | **Poglądowo / nauka** | Priorytetem jest wiarygodny obraz przepływu, płynne animacje i krótki czas liczenia. Walidacja tylko na przypadkach analitycznych, bez testów zbieżności siatki ani eksportu do OpenFOAM |
| 17 | Naczynia | **Wszystkie**: tętniaki mózgowe, duże tętnice, całe drzewo, żyły | Dwa poziomy modelu: sieć 1D dla całego drzewa i żył, 3D dla wybranego fragmentu (tętniak, zwężenie, bifurkacja) |
| 18 | Backend 3D | **Decyzja po spike'u S0** | S0 mierzy PyTorch-MPS i Numba-CPU na M4 Pro i wybiera jeden backend |
| 19 | Kolejność | **Teraz, przed AI** | E10 = Symulacje. Potem AI segmentacja, rejestracja i fuzja |

## 1. Ocena wykonalności

**Wykonalne w obecnej architekturze, bez przebudowy.** Większość potrzebnych elementów już istnieje:

| Potrzebne | Już jest |
|---|---|
| Geometria naczynia | `filtry/naczyniowosc` (Frangi) → `segmentacja/prog` → `wyspy` → segment; `mesh/z_segmentu`; `filtry/mapa_odleglosci` (promień) |
| Długie obliczenia | `JobManager` (lane `heavy`, postęp, anulowanie), cache wyników grafu, eventy przez WebSocket |
| Szybko i dokładnie | Ewaluator ma podgląd i pełną rozdzielczość. Podgląd to symulacja na grubej siatce |
| Mapy wyników | Prędkość i ciśnienie jako `wolumen` float32 działają od razu w widokach 2D/3D, z histogramem, profilem i statystykami |
| Przypadek testowy | `source/sample IA/`: CTA głowy i STL tętniaka |

Brakuje: pola wektorowego w czasie, linii środkowej, skalarów na wierzchołkach mesha, cząstek
i linii prądu w 3D, wspólnej osi czasu z odtwarzaniem, kosztu `sim` w ewaluatorze.

**Czego nie robimy:** podatnych ścian (FSI), turbulencji LES/DNS, siatek czworościennych ani
zewnętrznych solverów. Każda z tych rzeczy to osobny projekt, a przy celu poglądowym nic nie dodaje.

## 2. Model fizyczny

Krew: ρ = 1060 kg/m³, μ = 3,5 mPa·s, płyn newtonowski. Model Carreau-Yasuda jako opcja w S5.
Ściany są sztywne.

### 2.1 Sieć 1D, dla całego drzewa i żył (sekundy, liczona na żywo)

- Drzewo powstaje ze szkieletu maski (`skimage.morphology.skeletonize`, 3D). Promień w każdym
  punkcie bierzemy z mapy odległości. Gałęzie łączą węzły rozwidleń, a krótkie odgałęzienia
  (szum szkieletu) są przycinane wg długości w mm.
- Opór segmentu wynosi R = 8μL/(πr⁴) (Poiseuille). Układ równań w węzłach rozwiązuje
  `scipy.sparse`, dając ciśnienia w węzłach i przepływy w gałęziach.
- Na wylotach: podział wg prawa Murraya (Q ∝ r³), równy albo ręczny (opory końcowe).
- Tryb pulsacyjny: impedancja Womersleya per gałąź per harmoniczna krzywej wlotu (dziedzina
  częstotliwości, ok. 10 harmonicznych), co daje krzywe Q(t) i p(t) w każdej gałęzi. Bez kroku czasowego.
- Wynik: Q, ‹v›, Δp i WSS ≈ 4μQ/(πr³) per gałąź. Żyły liczymy tym samym modelem z presetem
  niskiego ciśnienia i płaską krzywą.

### 2.2 3D, dla wybranego fragmentu (Lattice Boltzmann)

- Liczymy na **siatce wokseli maski**, więc nie trzeba generować siatki. ROI jest wycinane
  automatycznie wokół zaznaczonych wlotów i wylotów, a maska resamplowana do kroku `dx` z suwaka jakości.
- Schemat D3Q19 z kolizją **regularyzowaną** (stabilna przy τ → 0,5, co wymusza lepkość
  krwi na drobnej siatce). Ściany: halfway bounce-back.
- Wlot: profil paraboliczny (ustalony) albo Womersleya (pulsacyjny) na płaszczyźnie prostopadłej
  do linii środkowej. Wylot: stałe ciśnienie albo podział jak w 1D. **Przedłużenia** wlotów
  i wylotów o 3–5 średnic (rura wzdłuż stycznej) sprawiają, że przepływ dochodzi do ROI rozwinięty.
- Jednostki: `dx` z jakości, `dt` z warunku Macha (u_lat ≤ 0,05). Przed startem szacujemy czas
  i RAM i pokazujemy je w karcie.
- Zbieżność stanu ustalonego: względna zmiana |u| < 1e-4 w oknie N kroków. W trybie pulsacyjnym
  2 cykle rozbiegowe i 1 cykl zapisywany (20–40 klatek).
- Zapis: pole w ROI `[t, k, j, i, 3]` float16, zarr + zstd (komórki poza płynem są zerami i dobrze
  się kompresują) oraz ciśnienie `[t, k, j, i]` float16.

### 2.3 Hemodynamika na ścianie

- WSS w wierzchołku mesha: prędkość próbkowana w odległości δ (ok. 1 woksel) wzdłuż normalnej
  do wewnątrz, WSS ≈ μ·|u_t|/δ. Dla celu poglądowego to wystarcza i jest tanie.
- Z klatek liczymy TAWSS, OSI i ciśnienie na ścianie. W tabeli: max/średnia/percentyle oraz
  odsetek powierzchni z niskim WSS (< 0,4 Pa).

## 3. Model danych i architektura

```
segment ─► [Drzewo] ─► [Warunki ♥] ─► [Przepływ 1D] ─► tabela + drzewo (Q, p, WSS na gałęziach)
              │             │
              └─────────────┴──► [Przepływ 3D] ─► pole ─┬─► [Hemodynamika] ─► mesh (WSS/TAWSS/OSI) + tabela
                                     ▲                  └─► [Pole → wolumen] ─► |v|, p, wirowość
                                  segment
```

### Nowe gniazda (`PortKind`)

| `kind` | Co to | Wartość |
|---|---|---|
| `drzewo` | Linia środkowa: węzły [LPS mm], gałęzie (polilinie + promień), końcówki, opcjonalne warunki i wyniki 1D | `DataValue` (JSON, małe) |
| `pole` | Prędkość (+ ciśnienie) w czasie, w ROI | `FieldValue`: uchwyt do `<ref>.field/` (24 hex, cache), geometria ROI, `frames`, `period`, `info.ref` = tło |

`FieldValue` trzeba dopisać do `value_from_json` (lekcja z segmentacji: inaczej po restarcie
do węzłów dociera None), do przycinania cache i do manifestu.

### Nowe typy parametrów

- `ends`: `[{id, p:[x,y,z], role:"in"|"out"|"wall", split?}]`. `clean_params` przypisuje końcówki
  do najbliższych końców drzewa, więc równe ustawienia dają ten sam klucz cache.
- `waveform`: `{preset, mean_ml_s, bpm, points?:[[t, q], …]}` (krzywa znormalizowana do 0..1 cyklu).

### Koszt `sim` w ewaluatorze

Nowa wartość `Cost = "sim"`: **nigdy** nie startuje automatycznie po bezczynności, tylko po ▶ na
karcie. Job zapisuje checkpoint co N kroków (`<key>.partial/`), więc po anulowaniu albo
zamknięciu aplikacji da się wznowić. Co kilka sekund wysyła migawkę |u| (podgląd na żywo
w widoku) i resztę zbieżności (sparkline na karcie).

### Mesh ze skalarami

Rozszerzenie formatu `.mesh/` (wstecznie zgodne): `scalars/<nazwa>.bin` (f32 `[N]` albo f16
`[T, N]`) + `meta.scalars: [{name, unit, range, frames}]`. `setMeshes` dostaje opcjonalny
`scalar` + LUT (vtk.js `scalarVisibility`); w czasie podmieniamy tylko tablicę skalarów, a geometrię zostawiamy.

### Pole w widokach

- **3D (`VolumeRenderer3D`, jedyne miejsce z vtk.js):**
  - `setStreamlines(lines, lut)`: polilinie z sidecara (RK4, interpolacja trójliniowa,
    wektoryzowane ziarna). „Płynący” efekt dają przesuwające się w czasie współrzędne tekstury
    lub LUT, bez przebudowy geometrii.
  - `setParticles(positions[frame])`: ok. 2–5 tys. punktów, tor liczony w sidecarze. Co klatkę
    animacji podmieniamy jeden bufor i wywołujemy `requestRender()`.
- **2D:** przekrój |u| przez endpoint `/fields/{ref}/slice?frame&axis&index` (binarnie, jak dziś)
  jako nakładka z colormapą, plus warstwa strzałek (składowe w płaszczyźnie, canvas jak `MarkupLayer2D`).
- **Oś czasu** `scene.time` (0..1 cyklu): jeden zegar dla wszystkich widoków. Odtwarzanie przez
  rAF działa tylko wtedy, gdy ▶ jest wciśnięte (inaczej nic nie rysujemy). Klatki pobierane z wyprzedzeniem i trzymane w LRU.

### Pliki

```
src/pratrd/sim/         tree.py (szkielet → graf), network.py (1D, Womersley), lbm/ (backend
                        wybrany w S0), bc.py (ROI, płaszczyzny, przedłużenia), wall.py (WSS/OSI),
                        tracers.py (linie prądu, cząstki), field_store.py (.field, slice)
src/pratrd/nodes/symulacja.py
src/pratrd/api/fields.py
app/src/lib/sim/        timeline.svelte.ts, Timeline.svelte, WaveformEditor.svelte,
                        EndsLayer3D.svelte, ArrowsLayer2D.svelte, SimCard.svelte (▶, ring, sparkline)
tests/test_sim.py       analityka (rura, bifurkacja, Womersley), zapis/odczyt pola
scripts/spike_lbm.py    S0, nie wchodzi do buildu
```

## 4. Node'y (domena „Symulacja”)

| Node | Wejścia → wyjścia | Parametry (fizyczne) | Koszt |
|---|---|---|---|
| **Drzewo naczyń** | segment → drzewo | wygładzenie [mm], min. gałąź [mm] | heavy |
| **Warunki** (stanowy) | drzewo → drzewo | `ends`, `waveform`, preset krwi, podział wylotów | light |
| **Przepływ 1D** | drzewo → drzewo + tabela | ustalony / pulsacyjny | light (na żywo) |
| **Przepływ 3D** | segment + drzewo → pole | jakość (`dx` mm), ustalony / pulsacyjny, cykle, klatki | **sim** |
| **Hemodynamika** | pole (+ mesh opc.) → mesh + tabela | wielkość: WSS / TAWSS / OSI / ciśnienie | heavy |
| **Pole → wolumen** | pole → wolumen | \|u\|, składowa, ciśnienie, wirowość; klatka albo średnia | light |

Linie prądu i cząstki nie są node'ami: to sposób wyświetlania `pole` (oko na karcie
i przełączniki w widoku), tak jak mesh pokazuje się dziś sam.

**Szablon grafu „♥ Przepływ”:** przycisk na karcie segmentu albo w palecie wstawia cały łańcuch
Drzewo → Warunki → 1D (+ 3D) podłączony do zaznaczonego segmentu. Od jednego kliknięcia jest
gotowy przepływ 1D, bez budowania grafu ręcznie.

## 5. UX: obrazkowo, mało tekstu

| Miejsce | Elementy (tekst tylko w tooltipach) |
|---|---|
| Warunki, w widoku 3D | Końcówki drzewa jako kółka. Klik przełącza ⬇ wlot (zielona strzałka do środka), ⬆ wylot (czerwona na zewnątrz) i ⊘ ścianę. Strzałki rosną z przepływem |
| Warunki, na karcie | Mini-schemat drzewa ze strzałkami. Miniatury krzywych (♥ szyjna, mózgowa, aorta, ▬ żyła). Krzywą przeciąga się jak próg na histogramie. Pokrętło ♥ bpm i ml/s. Chipy krwi (kropla / kropla+) |
| Przepływ 3D, karta | Suwak jakości z trzema ikonami gęstości siatki i paskami ⏱ czas i ▮ RAM (liczby w tooltipie). Duży ▶ i ⏹. `ProgressRing` z resztą zbieżności jako sparkline |
| Podczas liczenia | Widok co kilka sekund dostaje migawkę \|u\|, więc widać, jak przepływ się rozwija |
| Wynik w 3D | Pasek ikon w rogu: ≋ linie prądu, • cząstki, ▦ kolor ściany, ◐ duch tła. Pasek kolorów bez opisu (wartości po najechaniu) |
| Oś czasu | Pod widokami, gdy jest pole. Miniatura krzywej przepływu z kropką bieżącej fazy, ▶/⏸, prędkość ×¼ ×½ ×1. Przeciąganie kropki przewija cykl |
| Sonda | Klik w naczynie (narzędzie „sonda”) otwiera mini-wykres u(t) i p(t) przy kursorze. ⌘-klik wrzuca go do notatki, aparat na Tablicę |
| 2D | Nakładka \|u\| + strzałki, przełączane ikoną |
| Ostrzeżenia | Ikona ⚠ na karcie z tooltipem: „< 8 wokseli na średnicę”, „brak wlotu”, „wlot = wylot” |

Nowe ikony w `Icon.svelte`: przepływ, serce, wlot, wylot, ściana, cząstki, linie prądu, sonda,
play/pause, siatka (3 gęstości), kropla.
Skróty: `Spacja` = ▶/⏸ osi czasu (gdy Scena jest widoczna), `,` / `.` = klatka. Wpis w `ShortcutsModal`.

## 6. Etapy

Każdy etap kończy się działającą aplikacją, zielonymi testami i wpisem w `CHANGELOG.md`.

| Etap | Zakres | Kryterium „gotowe” |
|---|---|---|
| **S0 Spike** | `scripts/spike_lbm.py`: D3Q19 regularyzowany w NumPy (wzorzec), Numba-CPU i PyTorch-MPS; rura syntetyczna i ROI tętniaka z próbki | Tabela MLUPS, RAM i błędu Poiseuille'a w `03-wydajnosc.md`. **Decyzja o backendzie** (reguła: PyTorch, jeśli ≥ 3× szybszy; inaczej Numba, bo build jest lżejszy). Realny czas trybu pulsacyjnego |
| **S1 Drzewo + 1D** | Gniazdo `drzewo`, Drzewo naczyń, Warunki (końcówki w 3D, krzywe), Przepływ 1D (ustalony i Womersley), szablon „♥ Przepływ”, kolor gałęzi w 3D wg Q/WSS | Rura: Δp zgodne z Poiseuille'em ±1%. Symetryczna bifurkacja 50/50. Drzewo naczyń mózgu z próbki w < 1 s, zmiana bpm przelicza na żywo |
| **S2 Pole i widok** | `FieldValue` + `.field/`, endpoint przekrojów, Pole → wolumen, oś czasu, cząstki i linie prądu, skalary na meshu, 2D strzałki. Pole testowe z rozwiązania analitycznego | Animacja 3 tys. cząstek i mesha z kolorem WSS: p95 ≤ 18 ms/klatkę (WebKit @2x, jak w E7). Pole przetrwa restart |
| **S3 3D ustalony** | Solver z S0 w sidecarze: ROI, przedłużenia, wlot/wylot, koszt `sim`, checkpointy, migawki na żywo; Hemodynamika (WSS, ciśnienie) | Rura: profil paraboliczny ±5%. Bilans masy wlot−wyloty ≤ 2%. Tętniak z próbki: podgląd ≤ 30 s, pełna jakość ≤ 10 min, RAM ≤ 8 GB |
| **S4 Pulsacja** | Profil Womersleya na wlocie, cykle rozbiegowe, zapis klatek, TAWSS/OSI, pętla animacji cyklu, sonda u(t)/p(t) | Rura: profil Womersleya (α ≈ 4) zgodny jakościowo z analityką. Pełny cykl tętniaka w czasie z S0 i z postępem |
| **S5 Opcje** | Krew nienewtonowska, porównanie dwóch wariantów (różnica WSS), import 4D Flow MRI jako `pole` (dane mierzone) | Według potrzeb, każdy punkt osobno |

Po każdym etapie: `uv run pytest -q`, `ruff`, `pnpm check && pnpm test`, `cargo clippy`; nowe
biblioteki dopisane do `_DEPS` (`api/system.py`) i `sidecar.spec`; smoke test zamrożonego sidecara
przechodzi przez Przepływ 1D i krótki Przepływ 3D (S3).

## 7. Budżety wydajności (do potwierdzenia w S0)

| Operacja | Cel |
|---|---|
| Przepływ 1D (całe drzewo) | < 1 s, na żywo przy zmianie parametrów |
| 3D ustalony, podgląd (gruba siatka) | ≤ 30 s |
| 3D ustalony, pełna jakość (ROI tętniaka, `dx` ≈ 0,1–0,15 mm) | ≤ 10 min |
| 3D pulsacyjny (3 cykle) | szacunek od kilkudziesięciu minut do godzin, ustalany w S0 |
| Animacja w widokach | 60 fps, p95 ≤ 18 ms |
| RAM symulacji | ≤ 8 GB (ustawienie budżetu) |
| Dysk na pole (40 klatek, ROI) | ≤ 1 GB po kompresji |

Szacunek rzędu wielkości dla 3D: ROI 300³ = 27 mln komórek, D3Q19 × 2 bufory × float32 ≈ 4 GB
gęsto. Komórki płynu to w naczyniach zwykle 5–15%, więc przechowywanie tylko płynu zmniejsza
pamięć i czas kilkukrotnie. Jeden cykl przy `dx` = 0,1 mm i u_max = 1 m/s to ok. 10⁵ kroków.
Stąd tryb ustalony jako domyślny, a pulsacja jako świadomie uruchamiany długi job.

## 8. Ryzyka

| Ryzyko | Waga | Kontrola |
|---|---|---|
| **Warunki brzegowe pacjenta nieznane** (dominują nad błędem solvera) | wysoka | Cel poglądowy. Presety z literatury, wynik traktowany jako względny. Porównanie wariantów w grafie (S5) |
| **Rozdzielczość segmentacji.** 0,39 mm daje ok. 10 wokseli na średnicę małej tętnicy, a WSS jest na to wrażliwe | wysoka | Resampling ROI do `dx`, ostrzeżenie ⚠ < 8 wokseli na średnicę. Wygładzenie maski przed resamplingiem |
| **Stabilność LBM** przy τ ≈ 0,5 | średnia | Kolizja regularyzowana od początku, test rury w CI, automatyczne zmniejszenie u_lat (wolniej, ale stabilnie) i ⚠ zamiast błędnych wyników (NaN → przerwanie joba z komunikatem) |
| **Czas i RAM 3D** | średnia | Spike S0 przed resztą. Tylko komórki płynu, ROI, budżet RAM, checkpointy, tryb ustalony jako domyślny |
| **Backend.** PyTorch zwiększa build o setki MB, a Numba działa tylko na CPU | średnia | Decyzja w S0 wg reguły z §6. Jeden backend, NumPy tylko jako wzorzec w testach. PyTorch i tak wejdzie z etapem AI |
| **Pakowanie** (PyInstaller + torch/numba, 3 systemy) | średnia | `collect_all` w `sidecar.spec`, smoke test liczy krótki Przepływ 3D w zamrożonym buildzie. Windows/Linux bez GPU → CPU (wolniej, ale działa) |
| **Szkielet 3D zaszumiony** (fałszywe gałęzie, pętle przy stykających się naczyniach) | średnia | Przycinanie gałęzi < min. długości, rozcinanie pętli wg promienia. Końcówki do ręcznej korekty w Warunkach |
| **Żyły:** ściany się zapadają, są zastawki, słabe zakontrastowanie w fazie tętniczej | średnia | Dla żył domyślnie 1D z presetem. 3D tylko dla dobrze widocznych (zatoki). ⚠ na karcie |
| **Długie joby a graf** (auto-ewaluacja, cache, restart) | niska | Koszt `sim` tylko na ▶, checkpointy, wznawianie. Wynik w cache jak każdy inny |
| **Rozmiar pól na dysku** | niska | float16, zstd, tylko ROI, klatki z suwaka. Przycinanie cache tym samym budżetem co dziś |
| **Płynność animacji** (priorytet nr 1) | niska | Podmiana jednego bufora na klatkę, LUT/tekstura zamiast przebudowy geometrii, pomiar p50/p95 w S2 |
| **Zakres i wypalenie** | średnia | S1 jest samodzielnie użyteczny (1D dla całego drzewa). Każdy etap kończy się działającą funkcją |

## 9. Otwarte kwestie (rozstrzygane w trakcie, bez blokowania startu)

- Presety krzywych przepływu: wartości średnie z literatury (ICA ≈ 4–5 ml/s, MCA ≈ 2–3 ml/s,
  aorta wstępująca ≈ 80–90 ml/s, żyły: przepływ stały). Spisane w Dokumentacji przy node'zie Warunki.
- Czy pokazywać ciśnienie bezwzględne (mmHg, wymaga ciśnienia na wylocie) czy tylko Δp względem wylotu.
  Propozycja: domyślnie Δp, a ciśnienie bezwzględne jako opcja.
- Kolor gałęzi drzewa w 2D (przekrój linii środkowej) — dopiero po S2, jeśli będzie potrzebny.
