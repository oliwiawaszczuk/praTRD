# Design tokens (wyciągnięte z praSzczur)

W praSzczur kolory są wpisane na sztywno w każdym komponencie (np. `#ffc951` występuje 179 razy).
W praTRD te same wartości trafią **od początku** do zmiennych CSS w jednym miejscu.

## Kolory

| Token | Wartość | Użycie w praSzczur |
|---|---|---|
| `--bg-app` | `#333` | tło `body` |
| `--bg-boot` | `#222` | ekran startowy |
| `--bg-panel` | `#2a2a2a` | aktywna zakładka, content, pasek podzakładek |
| `--bg-panel-2` | `#262626` | panele drugiego planu |
| `--bg-deep` | `#1a1a1a` | inputy, płótna, karty (101 użyć) |
| `--bg-deepest` | `#111` | najgłębsze tła |
| `--accent` | `#ffc951` | akcent (żółty/złoty): aktywne zakładki, progress, focus |
| `--accent-a10..a50` | `rgba(255,201,81,.10/.15/.25/.3/.4/.5)` | tła/obwódki aktywnych elementów |
| `--text` | `#e0e0e0` | tekst podstawowy |
| `--text-strong` | `#f0f0f0` | nagłówki |
| `--text-dim-*` | `rgba(255,255,255,.6/.45/.35/.22)` | tekst drugorzędny → nieaktywny |
| `--line` | `rgba(255,255,255,.07–.12)` | obwódki, separatory |
| `--danger` | `#ff6b6b` | błędy |

Kolory gniazd node'ów (z `PORT_KIND_COLORS`) — świadomie **nie** w odcieniu akcentu:
`#5b9bd5` niebieski, `#f2994a` pomarańcz, `#b48ce0` fiolet, `#7bc47f` zieleń, `#4db6ac` turkus,
`#c0ca33` limonka, `#90a4ae` szaroniebieski, `#f06292` róż.

## Typografia

- Czcionka: **JetBrains Mono** (`@fontsource/jetbrains-mono` 400 + 600), wszędzie, także w inputach (`font-family: inherit`).
- Skala: zakładki `0.75rem / 600 / letter-spacing .05em`, podzakładki `0.66rem`, drobne etykiety `0.65–0.72rem`, tytuł boot `2rem / 700`.

## Kształty i ruch

- Zakładki: `border-radius: 8px 8px 0 0`, aktywna `box-shadow: 0 -2px 8px rgba(255,201,81,.1)`.
- Podzakładki: `border-radius: 6px`, aktywna = tło `accent .1` + obwódka `accent .3`.
- Przejścia `0.15s`, wejście layoutu `fadein .35s`, boot: logo z animacją `bouncespin` + `glow` w kolorze akcentu.
- Ciemny motyw jako jedyny (do potwierdzenia w Q&A).
