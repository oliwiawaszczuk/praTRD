# Referencja: praHand3D (github.com/praHand3D)

Pierwotny cel: system monitorowania ruchu dłoni, który wizualizuje w czasie rzeczywistym dane z czujników w rękawicy. Środowisko 3D pisane od zera. Ostatnie commity: czerwiec 2026, potem projekt porzucony.

| Repo | Stan | Zawartość |
|---|---|---|
| **praHangine** | v1.0.0 (2026-06-05), 36 commitów | C++20, CMake, OpenGL 3.3 Core (GLAD + GLFW), `App` (pętla), `Renderer` (VAO/VBO/EBO, MVP), `Camera` (LookAt + perspektywa), `SceneObject`, `SceneAnimation` (keyframe'y przy stałym fps). Shader: pozycja → jednolity pomarańczowy kolor (bez normalnych i oświetlenia). |
| **praPR4** | 4 commity | binarny format `.PR4`: magic `PR4`, wersja, liczniki; sekcje mesh (XYZ + indeksy uint16), obiekty (pos, quat, scale), animacje (keyframe'y przy stałym fps). Bez normalnych i UV. `AssetSystem` load/write. |
| **praMath** | – | Vec3/Vec4, Matrix4x4, Transform → macierz modelu. Testy GoogleTest. |
| **praFormatterPR4** | 11 commitów | dodatek do Blendera (`praBlendExte`: import/export/panel) + skrypt do przeładowania dodatku. |
| **praHand3D.github.io** | szablon | React + Vite, bez treści. |

## Co może być przydatne w praTRD (do potwierdzenia w Q&A)

- **Wiedza i koncepcje**: kamera orbitalna, transformacje (quaternion, TRS), pipeline mesh → GPU.
- **Format `.PR4`**: jako opcjonalny eksport meshy (np. po segmentacji → marching cubes).
- **Silnik C++**: osadzenie natywnego OpenGL w oknie Tauri jest trudne (wymaga osobnego okna lub renderu offscreen). Realnie silnik raczej nie będzie rendererem praTRD, chyba że to cel sam w sobie.
- Konwencje repo: `VERSION` + `CHANGELOG.md` (Keep a Changelog), testy jednostkowe.
