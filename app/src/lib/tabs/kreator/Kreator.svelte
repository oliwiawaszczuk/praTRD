<script lang="ts">
  // Kreator — the user's own nodes. Left: list + templates; then the card being built
  // (name, category, sockets, parameters), the Python code and the test panel. Saving
  // registers the node as "wlasne/<slug>": it appears in the Scena palette at once.
  import { onMount } from "svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { DOMAIN_COLOR } from "#lib/graph/registry.svelte.ts";
  import { PORT_COLORS } from "#lib/graph/types.ts";
  import { inTauri } from "#lib/core/tauri.ts";
  import { showError } from "#lib/ui/dialogs.svelte.ts";
  import CodeEditor from "./CodeEditor.svelte";
  import NodeBuilder from "./NodeBuilder.svelte";
  import TestPanel from "./TestPanel.svelte";
  import LibraryPanel from "./LibraryPanel.svelte";
  import {
    duplicate,
    exportNode,
    importNode,
    kreator,
    loadList,
    loadLibraries,
    newFromTemplate,
    openNode,
    remove,
    restore,
    runTest,
    save,
    setCode,
  } from "./kreator.svelte.ts";
  import { onEvent } from "#lib/core/events.svelte.ts";
  import { codeSkeleton, KIND_IN, TEMPLATES } from "./model.ts";

  let root = $state<HTMLDivElement>();
  let editor = $state<CodeEditor>();
  let ready = $state(false);
  let gallery = $state(false);
  let libsOpen = $state(false);
  let libSuggest = $state("");

  onMount(() => {
    void loadLibraries().catch(() => {}); // import completions
    restore()
      .catch((e) => showError("Nie udało się wczytać node'ów", e))
      .finally(() => (ready = true));
    const off = onEvent("node-types", () => void loadList());
    return off;
  });

  const d = $derived(kreator.draft);

  // squiggles: syntax error while typing, else the line of the last test's error / failed check
  const errors = $derived.by(() => {
    if (kreator.codeError?.line) return [{ line: kreator.codeError.line, message: kreator.codeError.message, severity: "error" as const }];
    const r = kreator.result;
    if (!r || kreator.resultStale) return [];
    const out: { line: number; message: string; severity: "error" | "warning" }[] = [];
    if (r.error?.line) out.push({ line: r.error.line, message: r.error.message, severity: "error" });
    for (const c of r.checks)
      if (c.line && c.level === "fail" && c.line !== r.error?.line) out.push({ line: c.line, message: c.message ?? c.label, severity: "warning" });
    return out;
  });

  const visible = () => !!root?.offsetParent; // the tab stays mounted while hidden
  function onKey(e: KeyboardEvent): void {
    if (!visible() || !d || !(e.metaKey || e.ctrlKey)) return;
    if (e.key === "s") {
      e.preventDefault();
      void save();
    } else if (e.key === "Enter") {
      e.preventDefault();
      void runTest();
    }
  }

  function insertSnippet(text: string): void {
    editor?.insert(text);
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="kreator" bind:this={root}>
  <aside class="list">
    <div class="lhead">
      <span>Moje node'y</span>
      <button class="ib" title="Nowy node z szablonu" onclick={() => (gallery = !gallery)}><Icon name="plus" size={13} /></button>
      {#if inTauri()}<button class="ib" title="Importuj plik .pratrdnode" onclick={importNode}><Icon name="folderIn" size={13} /></button>{/if}
    </div>
    <div class="items">
      {#each kreator.list as n (n.slug)}
        <div class="item" class:on={d?.slug === n.slug}>
          <button class="iname" onclick={() => void openNode(n.slug).catch((e) => showError("Nie udało się otworzyć", e))} title={n.error || `wlasne/${n.slug}`}>
            <i style:background={DOMAIN_COLOR[n.domain] ?? "var(--accent)"}></i>
            <span>{n.label}</span>
            {#if n.error}<span class="err"><Icon name="alert" size={11} /></span>{/if}
            {#if d?.slug === n.slug && kreator.dirty}<span class="dirty" title="Niezapisane zmiany"></span>{/if}
          </button>
          <div class="iact">
            {#if inTauri()}<button title="Eksport do pliku .pratrdnode" onclick={() => void exportNode(n.slug).catch((e) => showError("Eksport nie powiódł się", e))}><Icon name="export" size={11} /></button>{/if}
            <button title="Usuń" onclick={() => void remove(n.slug).catch((e) => showError("Nie udało się usunąć", e))}><Icon name="trash" size={11} /></button>
          </div>
        </div>
      {/each}
      {#if d && !d.slug}
        <div class="item on">
          <span class="iname"><i style:background={DOMAIN_COLOR[d.manifest.domain]}></i><span>{d.manifest.label || "Nowy node"}</span><span class="dirty"></span></span>
        </div>
      {/if}
      {#if ready && !kreator.list.length && !d}<div class="none">Jeszcze nic — wybierz szablon</div>{/if}
    </div>
  </aside>

  {#if !ready}
    <div class="center"><ProgressRing size={30} /></div>
  {:else if !d || gallery}
    <div class="center">
      <div class="gallery">
        <h3>Nowy node</h3>
        <p>Wybierz punkt startu — wszystko zmienisz na karcie i w kodzie.</p>
        <div class="tiles">
          {#each TEMPLATES as t (t.id)}
            <button
              class="tile"
              onclick={async () => {
                await newFromTemplate(t);
                gallery = false;
              }}
            >
              <svg width="96" height="46" viewBox="0 0 96 46">
                <rect x="28" y="6" width="40" height="34" rx="6" fill="var(--bg-panel-2)" stroke={DOMAIN_COLOR[t.manifest.domain] ?? "var(--line-3)"} stroke-width="1.5" />
                {#each t.ports[0] as k, i (i)}
                  {@const y = 23 + (i - (t.ports[0].length - 1) / 2) * 12}
                  <line x1="6" y1={y} x2="28" y2={y} stroke={PORT_COLORS[k]} stroke-width="1.5" opacity="0.6" />
                  <circle cx="28" cy={y} r="4" fill={PORT_COLORS[k]} />
                {/each}
                {#each t.ports[1] as k, i (i)}
                  {@const y = 23 + (i - (t.ports[1].length - 1) / 2) * 12}
                  <line x1="68" y1={y} x2="90" y2={y} stroke={PORT_COLORS[k]} stroke-width="1.5" opacity="0.6" />
                  <circle cx="68" cy={y} r="4" fill={PORT_COLORS[k]} />
                {/each}
                <text x="48" y="27" text-anchor="middle" font-size="10" fill="var(--text-dim-2)">py</text>
              </svg>
              <b>{t.label}</b>
              <small>{t.hint}</small>
            </button>
          {/each}
        </div>
        {#if d}<button class="back" onclick={() => (gallery = false)}>Wróć do „{d.manifest.label}”</button>{/if}
      </div>
    </div>
  {:else}
    <div class="main">
      <div class="top">
        <span class="name">{d.manifest.label || "Bez nazwy"}</span>
        {#if kreator.dirty}<span class="badge">niezapisany</span>{/if}
        <span class="sp"></span>
        <button class="tb" title="Duplikuj jako nowy node" onclick={duplicate}><Icon name="layers" size={13} />Duplikuj</button>
        <button class="tb primary" disabled={kreator.saving || !kreator.dirty} title="Zapisz i dodaj do palety (⌘/Ctrl + S)" onclick={save}>
          {#if kreator.saving}<ProgressRing size={13} />{:else}<Icon name="check" size={13} />{/if}Zapisz
        </button>
      </div>
      <div class="cols">
        <div class="cardcol">
          <NodeBuilder />
          <div class="tip">
            <Icon name="info" size={12} />
            <span
              >Etykiety na karcie są dla Ciebie (PL), nazwy pod nimi — dla kodu (EN): <code>inputs.…</code>, <code>params.…</code>, klucze w <code>return</code>.
              Klik w nazwę zmienia ją. Parametry fizyczne w mm.</span
            >
          </div>
        </div>
        <div class="codecol">
          <div class="chips">
            {#if d.manifest.inputs.length}
              <span class="grp" title="Wejścia — połączenia z grafu"><Icon name="input" size={11} /></span>
              {#each d.manifest.inputs as p (p.id)}
                <button class="cchip" style:--c={PORT_COLORS[p.kind]} title="{p.label}: {KIND_IN[p.kind]}" onclick={() => insertSnippet(`inputs.${p.id}`)}
                  ><i></i>inputs.{p.id}</button
                >
              {/each}
            {/if}
            {#if d.manifest.params.length}
              <span class="grp par" title="Parametry — suwaki na karcie"><Icon name="sliders" size={11} /></span>
              {#each d.manifest.params as p (p.key)}
                <button class="cchip par" title={p.label} onclick={() => insertSnippet(`params.${p.key}`)}>params.{p.key}</button>
              {/each}
            {/if}
            <button class="cchip ctx" title="Pasek postępu na karcie (i punkt anulowania)" onclick={() => insertSnippet("ctx.progress(0.5)")}>ctx.progress</button>
            <span class="sp"></span>
            <button class="cchip lib" class:on={libsOpen} title="Biblioteki: wbudowane i doinstalowanie z PyPI" onclick={() => (libsOpen = !libsOpen)}>
              <Icon name="package" size={12} />Biblioteki
            </button>
            <button
              class="cchip ghost"
              title="Wstaw szkielet run() dla obecnych wejść, wyjść i parametrów (zastępuje kod)"
              onclick={() => setCode(codeSkeleton(d.manifest))}><Icon name="undo" size={11} />szkielet</button
            >
          </div>
          <div class="edwrap">
          <CodeEditor
            bind:this={editor}
            value={d.code}
            manifest={d.manifest}
            {errors}
            onchange={setCode}
            onsave={() => void save()}
            onrun={() => void runTest()}
          />
            {#if libsOpen}
              <LibraryPanel
                suggest={libSuggest}
                onimport={(line) => editor?.addImport(line)}
                onclose={() => {
                  libsOpen = false;
                  libSuggest = "";
                }}
              />
            {/if}
          </div>
          {#if kreator.codeError}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <div class="cerr" onclick={() => kreator.codeError?.line && editor?.goto(kreator.codeError.line)}>
              <Icon name="alert" size={12} />Linia {kreator.codeError.line}: {kreator.codeError.message}
            </div>
          {/if}
        </div>
        <div class="testcol">
          <TestPanel
            ongoto={(l) => editor?.goto(l)}
            onlibraries={(spec) => {
              libSuggest = spec;
              libsOpen = true;
            }}
          />
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .kreator {
    flex: 1;
    min-width: 0;
    height: 100%;
    display: flex;
    overflow: hidden;
  }
  .list {
    width: 210px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--line-1);
  }
  .lhead {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 10px 10px 8px 14px;
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-dim-2);
  }
  .lhead span {
    flex: 1;
  }
  .ib {
    display: flex;
    padding: 4px;
    color: var(--text-dim-2);
    background: none;
    border: 1px solid var(--line-2);
    border-radius: 6px;
    cursor: pointer;
  }
  .ib:hover {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .items {
    flex: 1;
    overflow-y: auto;
    padding: 0 6px 10px;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .item {
    display: flex;
    align-items: center;
    border: 1px solid transparent;
    border-radius: 6px;
  }
  .item:hover {
    background: var(--hover);
  }
  .item.on {
    background: var(--accent-a15);
    border-color: var(--accent-a30);
  }
  .iname {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 8px;
    font: inherit;
    font-size: 0.72rem;
    text-align: left;
    color: var(--text-dim-1);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .item.on .iname {
    color: var(--accent);
  }
  .iname span:not(.err):not(.dirty) {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .iname i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .err {
    display: flex;
    color: var(--danger);
  }
  .dirty {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
  }
  .iact {
    display: flex;
    opacity: 0;
    padding-right: 4px;
  }
  .item:hover .iact {
    opacity: 1;
  }
  .iact button {
    display: flex;
    padding: 3px;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .iact button:hover {
    color: var(--text-strong);
  }
  .none {
    padding: 10px 8px;
    font-size: 0.66rem;
    color: var(--text-dim-4);
  }
  .center {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: auto;
  }
  .gallery {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 24px;
  }
  .gallery h3 {
    margin: 0;
    font-size: var(--fs-lg);
    color: var(--text-strong);
  }
  .gallery p {
    margin: 0 0 12px;
    font-size: 0.72rem;
    color: var(--text-dim-3);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, 150px);
    justify-content: center;
    gap: 10px;
    max-width: 820px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 14px 10px 12px;
    font: inherit;
    color: var(--text-dim-1);
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: 12px;
    cursor: pointer;
    transition:
      border-color var(--t-fast),
      transform var(--t-fast);
  }
  .tile:hover {
    border-color: var(--accent-a70);
    transform: translateY(-2px);
  }
  .tile b {
    font-size: 0.78rem;
    color: var(--text-strong);
  }
  .tile small {
    font-size: 0.62rem;
    color: var(--text-dim-3);
  }
  .back {
    margin-top: 14px;
    font: inherit;
    font-size: 0.7rem;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .back:hover {
    color: var(--accent);
  }
  .main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .top {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    border-bottom: 1px solid var(--line-1);
  }
  .name {
    font-weight: 600;
    color: var(--text-strong);
    font-size: var(--fs-sm);
  }
  .badge {
    padding: 1px 7px;
    font-size: 0.58rem;
    color: var(--accent);
    border: 1px solid var(--accent-a40);
    border-radius: 999px;
  }
  .sp {
    flex: 1;
  }
  .tb {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    font: inherit;
    font-size: 0.7rem;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid var(--line-2);
    border-radius: 6px;
    cursor: pointer;
  }
  .tb:hover:not(:disabled) {
    color: var(--text-strong);
    border-color: var(--line-3);
  }
  .tb.primary {
    color: var(--bg-app);
    background: var(--accent);
    border-color: var(--accent);
    font-weight: 600;
  }
  .tb:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .cols {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .cardcol {
    width: 370px;
    flex-shrink: 0;
    overflow-y: auto;
    padding: 18px 18px 18px 22px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.05) 1px, transparent 0) 0 0 / 18px 18px;
    border-right: 1px solid var(--line-1);
  }
  .tip {
    display: flex;
    gap: 7px;
    font-size: 0.62rem;
    line-height: 1.5;
    color: var(--text-dim-3);
  }
  .tip code {
    color: var(--accent);
  }
  .codecol {
    flex: 1;
    min-width: 300px;
    display: flex;
    flex-direction: column;
  }
  .chips {
    flex-shrink: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--line-1);
  }
  .cchip {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 2px 7px;
    font: inherit;
    font-size: 0.62rem;
    color: var(--text-dim-1);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 999px;
    cursor: pointer;
  }
  .cchip i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--c);
  }
  .cchip.par {
    color: var(--param);
  }
  .cchip.ctx {
    color: var(--code-function);
  }
  .cchip.lib {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .cchip.lib.on {
    background: var(--accent-a15);
  }
  .grp {
    display: flex;
    margin: 0 1px 0 4px;
    color: var(--text-dim-3);
  }
  .grp:first-child {
    margin-left: 0;
  }
  .grp.par {
    color: var(--param);
  }
  .edwrap {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .cchip.ghost {
    color: var(--text-dim-3);
    background: none;
    border-style: dashed;
  }
  .cchip:hover {
    border-color: var(--accent-a70);
    color: var(--text-strong);
  }
  .cerr {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 10px;
    font-size: 0.66rem;
    color: var(--danger);
    background: var(--danger-a15);
    cursor: pointer;
  }
  .testcol {
    width: 330px;
    flex-shrink: 0;
    min-height: 0;
    border-left: 1px solid var(--line-1);
    background: var(--bg-panel);
  }
</style>
