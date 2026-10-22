# Referencja: 3D Slicer — mapa funkcji (do wyboru zakresu)

3D Slicer (Kitware/Brigham, VTK + ITK + Qt, Python scripting). Poniżej główne moduły. W Q&A wybieramy, co wchodzi do MVP, co później, a czego nie robimy.

| Moduł Slicera | Co robi | Odpowiednik node'a w praTRD? |
|---|---|---|
| **DICOM** (browser/import) | baza pacjent → badanie → seria, import folderu, tagi | źródło: `Seria DICOM` |
| **Data** (drzewo sceny) | hierarchia wolumenów, segmentacji, modeli, markupów | panel sceny |
| **Volumes** | okno/poziom (W/L), LUT, interpolacja, info o wokselach | `Okno/Poziom`, `LUT` |
| **Widoki 2D (MPR)** | osiowy / strzałkowy / czołowy, crosshair, synchronizacja | podgląd 2D przy node'ach |
| **Volume Rendering** | rendering bezpośredni (ray casting), presety (CT-Bone, CT-Soft…), transfer function | `Render wolumenu` |
| **Crop Volume / Resample** | wycięcie ROI, zmiana rozdzielczości | `Przytnij`, `Resampluj` |
| **Simple Filters** (SimpleITK) | ~100 filtrów: wygładzanie, progowanie, morfologia, gradient | domena **Filtry** |
| **Segment Editor** | próg, pędzel, gumka, wyspy, wypełnianie, grow-from-seeds, logiczne ops | domena **Segmentacja** |
| **Segmentations → Models** | maska → mesh (marching cubes / flying edges), wygładzanie, decymacja | `Maska → Mesh` |
| **Models** | wyświetlanie meshy, kolor, przezroczystość, przekroje | `Mesh` |
| **Markups** | punkty, linie (pomiar), kąty, krzywe, płaszczyzny, ROI | domena **Pomiary** |
| **Segment Statistics** | objętość, powierzchnia, statystyki intensywności | `Statystyki` |
| **Transforms / Registration** | liniowe/nieliniowe transformacje, rejestracja dwóch wolumenów | później |
| **Export** | STL/OBJ, NIfTI/NRRD, zrzuty ekranu | `Eksport` |
| **AI (TotalSegmentator, MONAI)** | automatyczna segmentacja organów | później? |

## Kluczowa różnica praTRD względem Slicera

W Slicerze operacje wykonuje się **imperatywnie** (klik w module → wynik w scenie, historia ginie).
W praTRD cały pipeline jest **grafem**: DICOM → filtry → segmentacja → mesh → pomiary. Można go zmienić, odtworzyć i zapisać per workspace. To odpowiednik Blender Geometry Nodes / Houdini dla danych medycznych.
