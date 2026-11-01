// Built-in guide per app tab (Markdown). Shown until the user edits a section in the
// Dokumentacja tab (edits are stored in app_docs.json and win from then on).

export interface TabDoc {
  key: string;
  title: string;
  body: string;
}

export const TAB_DOCS: TabDoc[] = [
  {
    key: "start",
    title: "Pierwsze kroki",
    body: `# Od DICOM do pomiaru w 5 krokach

1. **Dane** — przeciągnij folder z DICOM na okno (albo *Importuj*). Seria trafia do biblioteki workspace'u, dane są anonimizowane.
2. **Scena** — wybierz serię w panelu po prawej. Widzisz 3 przekroje i widok 3D; kursor jest wspólny.
3. **Graf** (dół Sceny) — spacja albo prawy klik dodaje node, np. *Seria → Przytnij → Próg*. Oko na karcie pokazuje wynik w widokach.
4. **Popraw** — *Edycja pędzlem* (pędzel, gumka, nożyce) w 2D i 3D.
5. **Zmierz** — *Statystyki segmentu*, *Markupy*, *Histogram*, *Profil*; tabelę zapisujesz do CSV, zrzut widoku wysyłasz na **Tablicę**.

> Wszystko w grafie jest odtwarzalne: zmiana wejścia przelicza całą resztę, wyniki są w cache.`,
  },
  {
    key: "dane",
    title: "Dane",
    body: `Import i biblioteka serii aktywnego workspace'u.

- **Import:** foldery DICOM (także DICOM-SEG), NIfTI, NRRD, MHA — przeciągnięciem na okno albo przyciskiem. Przed importem widać kandydatów (serie, fazy, ostrzeżenia).
- **Meshe** STL / OBJ / PLY (np. model ze Slicera) — tak samo; trafiają do biblioteki meshy, w Scenie używa ich node *Plik mesha*.
- **Anonimizacja** przy imporcie (dane pacjenta i UID-y usunięte).
- **Szczegóły serii:** wymiary, rozmiar woksela, modalność, okno; przeglądarka tagów DICOM.
- Dane są przechowywane jako piramida (szybkie przekroje i 3D nawet dla dużych serii).`,
  },
  {
    key: "scena",
    title: "Scena",
    body: `Widoki u góry, graf node'ów na dole (Ctrl+Spacja — jedno albo drugie na cały ekran).

## Widoki
- **2D:** kółko = przekrój, klik = kursor, PPM = okno/poziom, ⌘+kółko = zoom. Suwak u góry widoku przewija warstwy.
- **3D:** obrót myszą, gizmo (klik w kulkę = widok z tej strony), **5** = orto/perspektywa, prostokąty = gdzie są przekroje 2D.
- **Panel:** układ (2×2, 3D + 3, jeden), okno na histogramie, preset 3D, wygląd segmentu.

## Narzędzia (z kart node'ów)
- **Ziarna** (Region growing), **pędzel / gumka / nożyce** (Edycja pędzlem) — w 2D i 3D.
- **Markupy:** punkt, linijka, kąt, ROI — przeciągasz uchwyty, wartość zmienia się na żywo.
- **Zrzut na Tablicę:** ikona aparatu w rogu widoku.

## Filtry
- *Odszumianie* (dyfuzja) przed progowaniem zaszumionych serii; *Naczyniowość* → *Próg* (np. 0,3–1) → *Wyspy* → *Mesh* daje drzewo naczyń z CTA.
- *Maskuj wolumen* usuwa stół / kości przed renderingiem 3D, *Mapa odległości* + *Próg* = margines o dokładnej grubości w mm.
- Ciężkie filtry liczą się w tle z paskiem postępu; podgląd jest na zmniejszonym wolumenie.

## Meshe
- *Mesh z segmentu* → *Wygładź mesh* → *Decymacja*; *Plik mesha* wczytuje STL / OBJ / PLY, *Mesh → segment* robi z niego maskę.
- Wyświetlany mesh: w 3D powierzchnia (krycie w panelu), w 2D kontur przekroju w kolorze mesha.
- **Eksport** STL / OBJ / PLY: strzałka na karcie node'a (współrzędne LPS, jak DICOM i Slicer).`,
  },
  {
    key: "kreator",
    title: "Kreator",
    body: `Własne node'y: karta + kod w Pythonie. Zapisany node jest w palecie Sceny (znaczek *własny*).

## Karta — trzy strefy
- **Wejścia** (lewa, ikona →▢): dane z innych node'ów, czyli połączenia na grafie. W kodzie: \`inputs.<nazwa>\`.
- **Wyjścia** (prawa, ▢→): to, co zwraca \`run()\`, łączone dalej. W kodzie: klucz w \`return {"nazwa": …}\`.
- **Parametry** (dół, kolor turkusowy): suwaki i przełączniki na karcie, bez połączeń. W kodzie: \`params.<klucz>\`.
- Etykieta (PL) jest dla Ciebie, nazwa pod nią (EN) — dla kodu; klik zmienia. Kolor kropki = rodzaj gniazda, *opc* = może być niepodłączone (\`None\`), *[ ]* = wiele połączeń (lista).
- Te same kolory są w kodzie: \`inputs.image\` ma kolor gniazda, \`params.low\` turkus; nazwa, której nie ma na karcie, jest podkreślona na czerwono.

## Kod
\`\`\`python
def run(inputs, params, ctx):
    image = inputs.image                      # Volume
    return image.array > params.threshold    # bool -> segment on the input grid
\`\`\`
- **Volume:** \`.array\` (tylko do odczytu), \`.shape\` (k, j, i), \`.spacing\` (i, j, k) mm, \`.spacing_kji\` (dla scipy), \`.origin\`, \`.direction\`, \`.voxel_ml\`, \`.labels\`, \`.to_mm(ijk)\`, \`.to_ijk(xyz)\`. **Mesh:** \`.verts\` (mm), \`.faces\`. Tabela = dict, punkty = lista markupów, liczba = float.
- **Zwracasz** \`{output: value}\` (albo samą wartość przy jednym wyjściu): tablica o kształcie wejścia → wolumen / segment (bool) / segmentacja, \`(verts, faces)\` → mesh, lista słowników → tabela, liczba, lista \`[x, y, z]\` → punkty.
- **ctx:** \`ctx.progress(0.5)\` (pasek + anulowanie), \`ctx.preview\`, \`ctx.volume(arr, like=…, grid=…, name=…, window=(c, w), color=…, labels=[…])\`, \`ctx.grid(like, spacing=…, shape=…)\`, \`ctx.table(rows, columns=[(key, label, unit)], chart="bars")\`, \`ctx.mesh(v, f, name=…, color=…)\`.
- Kod piszemy po angielsku; parametry fizyczne w **mm** — wynik w podglądzie i w pełnej rozdzielczości jest wtedy ten sam.

## Biblioteki
- Przycisk **Biblioteki** nad kodem: wbudowane (numpy — \`np\` jest od razu, scipy, scikit-image, SimpleITK, nibabel, pydicom, pillow) — klik dopisuje \`import\` na górze kodu.
- **Dowolna paczka z PyPI:** wpisz nazwę (np. *scikit-learn*, *trimesh*, *opencv-python-headless*) → *Instaluj*. Trafia do folderu danych appki; wbudowane numpy/scipy… zostają w swoich wersjach (konflikt wersji = ostrzeżenie).
- Brakujący \`import\` w teście → przycisk *Zainstaluj …* i test od nowa.

## Test
- Wejście z **fantomu** (kula w szumie, woksel 0,8 × 0,8 × 1,5 mm — łapie kod ignorujący spacing), z **serii** albo z **node'a otwartego grafu**.
- **Kontrole:** składnia, wszystkie wyjścia, NaN/Inf, pusta / pełna maska, stały wolumen, zmiana typu, czas. Własne: \`def test(result, inputs, params): assert …\`.
- Błąd wskazuje linię w kodzie (klik → skok). \`print()\` i ostrzeżenia numpy trafiają do konsoli.

## Wymiana
Strzałka przy node'ie = plik *.pratrdnode* (karta + kod); import otwiera go jako szkic — zajęta nazwa = pytanie przy zapisie, nigdy nadpisanie.`,
  },
  {
    key: "tablica",
    title: "Tablica",
    body: `Swobodna tablica (jak Miro) — globalna, niezależna od workspace'u.

- Obrazy: przeciągnij, wklej (⌘V) albo **zrzut z widoku Sceny** (ikona aparatu) — trafia na ostatnio otwartą tablicę, z podpisem.
- Tekst (**T**), kształty, pędzel (**P**), warstwy (**↑/↓**), cofanie (**⌘Z**).
- **F** — pokaż wszystko; eksport całej tablicy do PNG.`,
  },
  {
    key: "notatki",
    title: "Notatki",
    body: `Notatki tekstowe — globalne, z wyszukiwarką (strzałki + Enter).

- Pierwsza linia staje się tytułem.
- **Pinezka** przypina notatkę do pływającego notatnika nad całą aplikacją.
- **⌘/Ctrl + klik** na wartości (pomiar, komórka tabeli, kursor) dopisuje ją do przypiętej notatki; zwykły klik kopiuje do schowka.`,
  },
  {
    key: "dokumentacja",
    title: "Dokumentacja",
    body: `Ten poradnik. **Tryb edycji** (przycisk u góry) zamienia każdą sekcję w edytor Markdown — zmiany zapisują się same.

- **Node'y** — opis edytowany tutaj pokazuje się też pod **(i)** na karcie node'a.
- **Poradniki** — własne strony (dodawanie, kolejność przeciąganiem, usuwanie w trybie edycji).`,
  },
  {
    key: "ustawienia",
    title: "Ustawienia",
    body: `- **Workspace'y:** przełączanie, nowy, eksport / import.
- **Wydajność:** ile wokseli trafia do GPU w widoku 3D; ile miejsca na dysku mogą zająć wyniki node'ów (najstarsze są usuwane).
- **Import:** domyślna anonimizacja (profil DICOM Basic, stały pseudonim pacjenta).
- **Diagnostyka:** stan silnika i jego bibliotek.`,
  },
];
