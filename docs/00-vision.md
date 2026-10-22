# praTRD: wizja (po Q&A, 2026-10-22)

## Jednym zdaniem
Wrzucam plik lub folder DICOM, oglądam go w 3D i w przekrojach 2D, a operacje na nim (filtry, segmentacja, mesh, pomiary) buduję jako **graf node'ów**, zapisany w workspace.

## Filary
1. **Node Graph 3D**: główna funkcja. Silnik w stylu praSzczur (typowane gniazda, memoizacja, ciężkie dane w backendzie), ale z typami danych 3D (wolumen, maska, mesh, punkty, transformacja…).
2. **Workspace'y i ustawienia** jak w praSzczur.
3. **Widok 3D + MPR**: obracanie, przekroje, rendering wolumenu.
4. **Wygląd praSzczur**: ciemny motyw, akcent `#ffc951`, JetBrains Mono.
5. **Build na macOS, Windows i Linux** przez GitHub Actions.

## Ustalenia
- Narzędzie na studia i badania, dla jednej osoby. Dane: CT, MRI, PET/USG/mikroskopia, gotowe segmentacje.
- Optymalizacja pod duże dane od początku.
- MVP: Segmentacja + Pomiary. Później: Mesh, filtry, AI, rejestracja.
- Szczegóły: `01-qa.md`, plan: `02-plan.md`.
