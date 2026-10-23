# Wydajność na dużych danych (E7, wersja 0.1.0)

Pomiar: `uv run python scripts/bench_large.py dicom|nifti` — prawdziwy sidecar, syntetyczne dane
podobne do CT (powietrze, ciało, kręgosłup, naczynia z kontrastem, szum). Czas = cały krok przez
HTTP; pamięć = szczyt RSS sidecara razem z procesami dekodującymi (z tym, co zostało w pamięci
podręcznej po poprzednich krokach). MacBook (Apple Silicon, 12 rdzeni, 24 GB RAM).

## Seria DICOM 512 × 512 × 2000 (int16, ~1 GB, 2000 plików)

| krok | czas | szczyt pamięci |
|---|---|---|
| skan folderu | 0,43 s | 157 MB |
| import (dekodowanie, piramida, statystyki) | 2,84 s | 786 MB |
| przekrój osiowy, losowy (zimny) | p50 16 / p95 17 ms | 1,3 GB |
| przekrój czołowy / strzałkowy (zimny) | p50 52–55 / p95 58–61 ms | 1,6 GB |
| wolumen do 3D (poziom 1, 125 MB) | 0,10 s | 1,8 GB |
| graf — podgląd: próg → wyspy → statystyki | 0,32 s | 1,8 GB |
| graf — pełna rozdzielczość: próg → wyspy → statystyki | 8,3 s | 5,5 GB |
| region growing (naczynie), pełna | 1,25 s | 7,0 GB |
| nożyce z kamery 3D (perspektywa), pełna | 3,0 s | 7,1 GB |

## Wolumen NIfTI 1024 × 1024 × 1000 (int16, ~2 GB)

| krok | czas | szczyt pamięci |
|---|---|---|
| import | 4,72 s | 0,7 GB |
| przekrój dowolnej osi, losowy | p50 57–62 / p95 60–74 ms | 1,4–1,7 GB |
| wolumen do 3D (poziom 1, 250 MB) | 0,15 s | 1,7 GB |
| graf — podgląd: próg → wyspy → statystyki | 0,44 s | 1,8 GB |
| graf — pełna: próg → wyspy → statystyki | 15,8 s | 6,4 GB |
| region growing, pełna | 3,35 s | 6,6 GB |
| nożyce 3D, pełna | 6,45 s | 6,5 GB |

## Interfejs (WebKit @2x, ten sam wolumen 2 GB)

| gest | wynik |
|---|---|
| pierwszy obraz 3D / docelowy poziom | 0,38 s / 0,88 s |
| przewijanie przekrojów (120 warstw, ruch co 16 ms) | p50 16 / p95 18 ms na klatkę |
| obrót 3D | p50 16 / p95 18 ms na klatkę |

## Co poprawiono w E7

Przed poprawkami pełny łańcuch na serii 1 GB trwał **15 s przy 7,9 GB** (8× danych):

- licznik wokseli segmentu (`label_stats`) robił `bincount` na całej masce → 4 GB kopii `intp`;
  teraz spis etykiet pochodzi z histogramu zapisu (jedno przejście), a dla masek 0/1 z
  `count_nonzero` (~100× szybciej);
- Próg liczy maskę warstwami prosto do wyniku (zamiast trzech pełnych kopii), maska bool trafia
  do zapisu jako widok uint8 bez kopiowania;
- Wyspy: jeden obraz etykiet (zamiast dwóch po 4 B/woksel), rozmiary liczone kawałkami,
  wynik przez tablicę „zostaw/usuń”;
- wynik node'a trafia od razu do pamięci podręcznej tablic — następny node nie dekoduje go z dysku;
- region growing bez zbędnego progowania kopii.

Po: **8,3 s przy 5,5 GB** (seria 1 GB), Próg 5,5 s → 2,0 s, region growing 4,7 s → 1,25 s.

## Meshe (E8)

CTA głowy 512² × 621, segment kości/kontrastu (≥ 250 HU, największa wyspa, 686 ml), Apple M, pełna rozdzielczość:

| Krok | Czas | Wynik |
|---|---|---|
| Mesh z segmentu (σ 0,3 mm, marching cubes warstwami po 64) | 4,3 s | 7,08 mln △, 685,1 ml (−0,2%) |
| Decymacja do 25% | ~1 s | 1,77 mln △, 685,0 ml |
| Taubin 20 iteracji (829 tys. △) | 0,25 s | objętość ±0,1% |
| Mesh → segment (wokselizacja promieniami, tylko pudełko mesha) | 0,28 s (duży) / 1 ms (STL tętniaka) | 0,067% wokseli różnych od maski źródłowej |
| Miniatura karty (7 mln △) | 0,96 s, raz | `thumb.png` obok mesha |

Widoki (WebKit @2x, mesh 1,77 mln △ → do widoku kopia LOD 1,5 mln △, robiona raz):
obrót 3D 9,7 ms/klatkę (`benchmarkOrbit`), przeciąganie 3D p50 17 / p95 19 ms, przewijanie 2D
z konturem przekroju p50 17 / p95 19 ms.

Objętość mesha vs segmentu zależy od σ: na strukturze 686 ml −0,1% (σ 0) … −1,2% (σ 0,5 mm);
na drobnej, poszarpanej masce (≥ 1300 HU, 42 ml) −1,3% (σ 0) … −17,6% (σ 0,5 mm) — stąd
domyślne σ = 0,3 mm.

## Filtry (E9)

Ta sama seria CTA 512² × 621 (163 M wokseli, int16), pełna rozdzielczość, Apple M; „szczyt” = RSS
całego procesu (sam wolumen + maska testowa ≈ 0,9 GB):

| Filtr | Czas | Szczyt RAM |
|---|---|---|
| Maskuj wolumen | 0,1 s | 0,9 GB |
| Arytmetyka (A − B) | 0,15 s | 1,4 GB |
| Wyostrz (σ 1 mm) | 1,0 s | 1,4 GB |
| Mapa odległości | 1,4 s | 2,6 GB |
| Krawędzie: gradient / LoG (σ 1 mm) | 2,5 s | 1,7–1,9 GB |
| Korekcja N4 (×4, 50 it.) | 7,0 s | 1,4 GB (było 5,3 GB przed liczeniem pola warstwami) |
| Dyfuzja gradientowa / krzywiznowa ×5 | 12,9 / 14,8 s | 2,7 GB |
| Naczyniowość (0,5–2 mm, 3 skale) | 34 s | 2,9 GB (całość naraz: 26 s / 4,2 GB) |
| Morfologia szarości: top-hat, kula 2 mm | ~60 s | 1,3 GB |

Podgląd (poziom ≤ 16 M wokseli) jest ok. 10× szybszy. Filtr bilateralny (187 s) odrzucony.

## Wskazówki

- Zalecany RAM: ok. 3–4 × rozmiar największego wolumenu przetwarzanego w pełnej rozdzielczości
  (podgląd i oglądanie potrzebują dużo mniej).
- Dla bardzo dużych danych najpierw **Przytnij** (box 3D) — każdy dalszy node pracuje tylko na ROI.
