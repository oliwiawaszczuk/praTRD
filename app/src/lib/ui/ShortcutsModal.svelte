<script lang="ts">
  // All keyboard / mouse shortcuts of the app, grouped by where they work. "?" opens it.
  import Icon from "./Icon.svelte";
  import { closeShortcuts, openShortcuts, shortcutsOpen, type ShortcutSection } from "./shortcuts.svelte.ts";

  const SECTIONS: { id: ShortcutSection; title: string; groups: { title: string; items: [string, string][] }[] }[] = [
    {
      id: "ogolne",
      title: "Ogólne",
      groups: [
        {
          title: "Aplikacja",
          items: [
            ["?", "Ta lista skrótów"],
            ["⌘/Ctrl + klik na wartości", "Dopisz ją do przypiętej notatki (zwykły klik: kopiuj)"],
            ["Przeciągnij foldery / pliki na okno", "Import serii (na Tablicy: obrazy)"],
          ],
        },
      ],
    },
    {
      id: "scena",
      title: "Scena — widoki",
      groups: [
        {
          title: "Widoki 2D",
          items: [
            ["Kółko", "Następny / poprzedni przekrój"],
            ["Klik / przeciągnięcie", "Kursor (wszystkie widoki za nim)"],
            ["PPM + przeciągnięcie", "Okno / poziom (W/L)"],
            ["Shift + przeciągnięcie, środkowy", "Przesuwanie"],
            ["⌘/Ctrl + kółko", "Zoom"],
            ["Dwuklik", "Widok na cały obszar (kursor zostaje)"],
            ["F (nad widokami)", "Wyśrodkuj i przybliż na przecięciu płaszczyzn"],
          ],
        },
        {
          title: "Widok 3D",
          items: [
            ["Przeciągnięcie", "Obrót (z narzędziem: Shift + przeciągnięcie)"],
            ["Kółko", "Zoom"],
            ["5 (nad widokiem)", "Perspektywa ↔ ortograficzny"],
            ["Klik w kulkę gizma", "Widok z tej strony"],
          ],
        },
        {
          title: "Narzędzia",
          items: [
            ["[ / ]", "Mniejszy / większy pędzel"],
            ["Esc", "Zakończ narzędzie (najpierw: porzuć niedokończony markup)"],
            ["⌘/Ctrl + Z, ⌘/Ctrl + Shift + Z", "Cofnij / ponów (pędzel, nożyce, markupy, graf)"],
            ["Ctrl + Spacja", "Widoki albo graf na cały ekran"],
          ],
        },
      ],
    },
    {
      id: "graf",
      title: "Graf node'ów",
      groups: [
        {
          title: "Edycja",
          items: [
            ["Spacja", "Dodaj node (wyszukiwarka)"],
            ["Prawy klik", "Dodaj node w tym miejscu"],
            ["Delete / Backspace", "Usuń zaznaczone"],
            ["⌘/Ctrl + D", "Duplikuj"],
            ["⌘/Ctrl + A", "Zaznacz wszystko"],
            ["F", "Dopasuj widok"],
            ["Esc", "Odznacz"],
          ],
        },
      ],
    },
    {
      id: "tablica",
      title: "Tablica",
      groups: [
        {
          title: "Narzędzia",
          items: [
            ["W", "Kursor (zaznaczanie)"],
            ["T", "Tekst w miejscu kursora"],
            ["P", "Pędzel"],
            ["Shift (rysując kształt)", "Kwadrat / koło"],
            ["Esc", "Wróć do zaznaczania"],
          ],
        },
        {
          title: "Widok i obiekty",
          items: [
            ["Kółko / Spacja + przeciąganie", "Przesuwanie"],
            ["⌘/Ctrl + kółko", "Zoom"],
            ["F", "Pokaż wszystko"],
            ["⌘/Ctrl + C / V", "Kopiuj / wklej (wklej obraz ze schowka)"],
            ["Delete / Backspace", "Usuń zaznaczone"],
            ["↑ / ↓", "Warstwa wyżej / niżej"],
            ["⌘/Ctrl + Z, ⌘/Ctrl + Shift + Z", "Cofnij / ponów"],
          ],
        },
      ],
    },
  ];

  const open = $derived(shortcutsOpen());
  const shown = $derived(open === "all" ? SECTIONS : SECTIONS.filter((s) => s.id === open));

  function onKey(e: KeyboardEvent): void {
    const t = (e.target as HTMLElement)?.tagName;
    if (open && e.key === "Escape") {
      e.stopPropagation();
      closeShortcuts();
    } else if (e.key === "?" && t !== "INPUT" && t !== "TEXTAREA" && !e.metaKey && !e.ctrlKey) {
      if (open) closeShortcuts();
      else openShortcuts("all");
    }
  }
</script>

<svelte:window onkeydowncapture={onKey} />

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={closeShortcuts}>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="box" role="dialog" aria-label="Skróty" tabindex="-1" onclick={(e) => e.stopPropagation()}>
      <header>
        <Icon name="keyboard" size={16} />
        <b>Skróty</b>
        <nav>
          <button class:on={open === "all"} onclick={() => openShortcuts("all")}>Wszystkie</button>
          {#each SECTIONS as s (s.id)}
            <button class:on={open === s.id} onclick={() => openShortcuts(s.id)}>{s.title}</button>
          {/each}
        </nav>
        <button class="x" title="Zamknij (Esc)" onclick={closeShortcuts}>✕</button>
      </header>
      <div class="cols">
        {#each shown as s (s.id)}
          {#each s.groups as g (g.title)}
            <section>
              <h5>{s.title} · {g.title}</h5>
              {#each g.items as [k, d] (k)}
                <div class="row"><span class="k">{k}</span><span class="d">{d}</span></div>
              {/each}
            </section>
          {/each}
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--backdrop);
    animation: fade 0.15s ease;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .box {
    width: min(920px, calc(100vw - 40px));
    max-height: 84vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-panel-2);
    border: 1px solid var(--accent-a25);
    border-radius: 12px;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    color: var(--accent);
    border-bottom: 1px solid var(--line-1);
  }
  header b {
    font-size: var(--fs-md);
  }
  nav {
    flex: 1;
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
  nav button {
    padding: 4px 10px;
    font: inherit;
    font-size: 0.64rem;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid var(--line-2);
    border-radius: 12px;
    cursor: pointer;
  }
  nav button.on {
    color: #111;
    background: var(--accent);
    border-color: var(--accent);
  }
  .x {
    font-size: 0.9rem;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .cols {
    padding: 14px 18px 18px;
    overflow-y: auto;
    columns: 2 380px;
    column-gap: 28px;
  }
  section {
    break-inside: avoid;
    margin-bottom: 16px;
  }
  h5 {
    margin-bottom: 6px;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-dim-3);
  }
  .row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding: 3px 0;
  }
  .k {
    flex-shrink: 0;
    max-width: 55%;
    padding: 2px 8px;
    font-size: 0.66rem;
    font-weight: 700;
    color: var(--accent);
    background: var(--accent-a10);
    border: 1px solid var(--accent-a25);
    border-radius: 6px;
  }
  .d {
    font-size: 0.7rem;
    color: var(--text-dim-1);
    text-align: right;
  }
</style>
