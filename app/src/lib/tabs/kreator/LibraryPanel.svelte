<script lang="ts">
  // What the node code can import: bundled libraries (click = import line at the top of the
  // code) and packages installed from PyPI into the app's own folder (any pip package;
  // bundled numpy/scipy… are never replaced).
  import { onMount } from "svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { installLibrary, libraries, loadLibraries, uninstallLibrary } from "./kreator.svelte.ts";
  import { showError } from "#lib/ui/dialogs.svelte.ts";

  let { onimport, onclose, suggest = "" }: { onimport: (line: string) => void; onclose: () => void; suggest?: string } = $props();

  let spec = $state("");
  $effect(() => {
    if (suggest) spec = suggest;
  });
  onMount(() => {
    void loadLibraries().catch((e) => showError("Nie udało się wczytać bibliotek", e));
  });

  const L = $derived(libraries.list);

  async function install(): Promise<void> {
    if (await installLibrary(spec)) spec = "";
  }
</script>

<svelte:window
  onpointerdown={(e) => {
    const t = e.target as HTMLElement;
    if (!t.closest(".lib") && !t.closest(".cchip.lib") && !t.closest(".dialog, .backdrop")) onclose();
  }}
  onkeydown={(e) => e.key === "Escape" && onclose()}
/>

<div class="lib">
  <header>
    <Icon name="package" size={14} />
    <b>Biblioteki</b>
    <span>klik = <code>import</code> na górze kodu</span>
    <button class="x" title="Zamknij" onclick={onclose}>✕</button>
  </header>

  {#if !L}
    <div class="wait"><ProgressRing size={22} /></div>
  {:else}
    <div class="scroll">
      <h6>Wbudowane</h6>
      {#each L.builtin as b (b.name)}
        <button class="row" title="Wstaw: {b.snippet}" onclick={() => onimport(b.snippet!)}>
          <span class="name">{b.name}<small>{b.version}</small><span class="about">{b.about}</span></span>
          <code>{b.snippet}</code>
        </button>
      {/each}

      <h6>Doinstalowane <small>(dowolne z PyPI)</small></h6>
      {#each L.user as u (u.name)}
        <div class="row user">
          <span class="name">{u.name}<small>{u.version}</small></span>
          <div class="mods">
            {#each u.modules ?? [] as mod (mod)}
              <button class="mod" title="Wstaw: import {mod}" onclick={() => onimport(`import ${mod}`)}>import {mod}</button>
            {/each}
          </div>
          <button class="del" title="Usuń {u.name}" onclick={() => void uninstallLibrary(u.name).catch((e) => showError("Nie udało się usunąć", e))}>
            <Icon name="trash" size={12} />
          </button>
        </div>
      {:else}
        <div class="none">Jeszcze nic — wpisz nazwę paczki poniżej.</div>
      {/each}
    </div>

    <form
      class="install"
      onsubmit={(e) => {
        e.preventDefault();
        void install();
      }}
    >
      {#if libraries.installing}
        <div class="busy">
          <ProgressRing size={14} />
          <span>{libraries.message || `Instalowanie ${libraries.installing}…`}</span>
        </div>
      {:else}
        <div class="field">
          <span class="pip">pip install</span>
          <input bind:value={spec} placeholder="np. scikit-learn" disabled={!L.canInstall} spellcheck="false" />
          <button class="go" disabled={!spec.trim() || !L.canInstall}><Icon name="download" size={12} />Instaluj</button>
        </div>
        <small class="hint">
          {#if L.canInstall}
            Paczka trafia do folderu danych appki; wbudowane numpy, scipy… zostają w swoich wersjach. Wymaga internetu.
          {:else}
            Instalacja niedostępna w tej wersji aplikacji (brak pip).
          {/if}
        </small>
      {/if}
    </form>
  {/if}
</div>

<style>
  .lib {
    position: absolute;
    top: 6px;
    right: 8px;
    z-index: 30;
    width: 380px;
    max-height: calc(100% - 12px);
    display: flex;
    flex-direction: column;
    background: var(--bg-panel-2);
    border: 1px solid var(--line-2);
    border-radius: 10px;
    box-shadow: 0 14px 40px rgba(0, 0, 0, 0.55);
    font-size: 0.68rem;
  }
  header {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 9px 10px;
    border-bottom: 1px solid var(--line-1);
    color: var(--accent);
  }
  header b {
    color: var(--text-strong);
  }
  header span {
    flex: 1;
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  header code {
    color: var(--code-keyword);
  }
  .x {
    padding: 0 4px;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .wait {
    display: flex;
    justify-content: center;
    padding: 24px;
  }
  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 6px;
  }
  h6 {
    margin: 6px 4px 4px;
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-dim-3);
  }
  h6 small {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 400;
  }
  .row {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 8px;
    font: inherit;
    text-align: left;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid transparent;
    border-radius: 6px;
    cursor: pointer;
  }
  .row:hover {
    background: var(--hover);
    border-color: var(--line-2);
  }
  .name {
    font-weight: 600;
    color: var(--text-strong);
  }
  .name small {
    margin-left: 6px;
    font-weight: 400;
    color: var(--text-dim-4);
  }
  .about {
    margin-left: 8px;
    font-weight: 400;
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  .row code {
    font-size: 0.6rem;
    color: color-mix(in srgb, var(--code-keyword) 55%, var(--text-dim-4));
  }
  .row:hover code {
    color: var(--code-keyword);
  }
  .row.user {
    position: relative;
    cursor: default;
    padding-right: 30px;
  }
  .mods {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
  }
  .mod {
    padding: 1px 6px;
    font: inherit;
    font-size: 0.58rem;
    color: var(--code-keyword);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 999px;
    cursor: pointer;
  }
  .mod:hover {
    border-color: var(--accent-a70);
  }
  .del {
    position: absolute;
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    padding: 3px;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .del:hover {
    color: var(--danger);
  }
  .none {
    padding: 4px 8px 8px;
    color: var(--text-dim-4);
  }
  .install {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 9px 10px 10px;
    border-top: 1px solid var(--line-1);
  }
  .field {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 3px 3px 8px;
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 7px;
  }
  .field:focus-within {
    border-color: var(--accent-a70);
  }
  .pip {
    color: var(--text-dim-3);
    white-space: nowrap;
  }
  .field input {
    flex: 1;
    min-width: 0;
    padding: 3px 0;
    font: inherit;
    color: var(--text-strong);
    background: none;
    border: 0;
    outline: none;
  }
  .go {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font: inherit;
    font-weight: 600;
    color: var(--bg-app);
    background: var(--accent);
    border: 0;
    border-radius: 5px;
    cursor: pointer;
  }
  .go:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .hint {
    font-size: 0.58rem;
    line-height: 1.45;
    color: var(--text-dim-3);
  }
  .busy {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 2px;
    color: var(--text-dim-1);
  }
  .busy span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
