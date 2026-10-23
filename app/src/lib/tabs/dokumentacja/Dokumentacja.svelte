<script lang="ts">
  // Dokumentacja — guide + how the app works (ported from praSzczur). Left: contents in three
  // collapsible groups (own pages, app tabs, node types from the sidecar registry). Right:
  // the section as rendered Markdown; "edit mode" turns every section into its Markdown
  // source (auto-saved). A node section starts with its ports and parameters drawn from the
  // schema (always up to date) and the description shared with "(i)" on node cards.
  import { onMount } from "svelte";
  import { marked } from "marked";
  import Icon from "#lib/ui/Icon.svelte";
  import { confirmAction } from "#lib/ui/dialogs.svelte.ts";
  import { domainLabels, loadNodeTypes, nodeTypes, DOMAIN_COLOR } from "#lib/graph/registry.svelte.ts";
  import { PORT_COLORS, PORT_LABELS, type NodeTypeSchema } from "#lib/graph/types.ts";
  import {
    appDocsLoaded,
    clearNodeDoc,
    clearTabDoc,
    createPage,
    deletePage,
    docPages,
    hasNodeDoc,
    loadAppDocs,
    movePage,
    nodeDoc,
    setNodeDoc,
    setTabDoc,
    tabDoc,
    takeDocSection,
    updatePage,
    type DocSection,
  } from "./appdocs.svelte.ts";
  import { TAB_DOCS } from "./docsSeed.ts";

  marked.setOptions({ gfm: true, breaks: true });

  const STAGES: Record<string, string> = { dane: "Dane", przetwarzanie: "Przetwarzanie", wynik: "Wynik" };
  // edited in the views / chosen from the library, not settings to document
  const HIDDEN_PARAMS = ["points", "strokes", "markups", "volume"];
  type Group = "pages" | "tabs" | "nodes";

  let edit = $state(false);
  let sel = $state<DocSection>({ kind: "tab", key: TAB_DOCS[0].key });
  let draft = $state("");
  let draftTitle = $state("");
  let open = $state<Record<Group, boolean>>({ pages: true, tabs: true, nodes: true });

  onMount(() => {
    if (!appDocsLoaded()) void loadAppDocs().then(() => reset(sel));
    if (!nodeTypes().length) void loadNodeTypes().catch(() => {});
  });

  // "(i)" on a node card asked for a section
  $effect(() => {
    const s = takeDocSection();
    if (s) {
      select(s);
      open[s.kind === "tab" ? "tabs" : s.kind === "node" ? "nodes" : "pages"] = true;
      void Promise.resolve().then(() => document.querySelector(".nav .item.on")?.scrollIntoView({ block: "nearest" }));
    }
  });

  const pages = $derived(docPages());
  const tabMeta = $derived(sel.kind === "tab" ? TAB_DOCS.find((t) => t.key === (sel as { key: string }).key) : undefined);
  const nodeDef = $derived(sel.kind === "node" ? nodeTypes().find((t) => t.id === (sel as { typeId: string }).typeId) : undefined);
  const page = $derived(sel.kind === "page" ? pages.find((p) => p.id === (sel as { id: string }).id) : undefined);

  const defaultBody = $derived(tabMeta?.body ?? nodeDef?.description ?? "");
  const body = $derived(
    sel.kind === "tab"
      ? tabDoc(sel.key) || defaultBody
      : sel.kind === "node"
        ? nodeDoc(sel.typeId, defaultBody)
        : (page?.body ?? ""),
  );
  const html = $derived(body.trim() ? (marked.parse(body) as string) : "");
  const overridden = $derived(sel.kind === "node" ? hasNodeDoc(sel.typeId) : sel.kind === "tab" ? !!tabDoc(sel.key) : false);
  const title = $derived(tabMeta?.title ?? nodeDef?.label ?? page?.title ?? "");

  const grouped = $derived.by(() => {
    const out: { domain: string; label: string; stages: { stage: string; items: NodeTypeSchema[] }[] }[] = [];
    for (const [domain, label] of Object.entries(domainLabels())) {
      const items = nodeTypes().filter((t) => t.domain === domain);
      if (!items.length) continue;
      const stages = Object.keys(STAGES)
        .map((stage) => ({ stage, items: items.filter((t) => t.stage === stage) }))
        .filter((s) => s.items.length);
      out.push({ domain, label, stages });
    }
    return out;
  });

  function reset(s: DocSection): void {
    if (s.kind === "tab") draft = tabDoc(s.key) || (TAB_DOCS.find((t) => t.key === s.key)?.body ?? "");
    else if (s.kind === "node") draft = nodeDoc(s.typeId, nodeTypes().find((t) => t.id === s.typeId)?.description ?? "");
    else {
      const p = docPages().find((x) => x.id === s.id);
      draft = p?.body ?? "";
      draftTitle = p?.title ?? "";
    }
  }
  function select(s: DocSection): void {
    sel = s;
    reset(s);
  }
  function onDraft(): void {
    if (sel.kind === "tab") setTabDoc(sel.key, draft);
    else if (sel.kind === "node") setNodeDoc(sel.typeId, draft);
    else updatePage(sel.id, { body: draft });
  }
  function restore(): void {
    if (sel.kind === "node") clearNodeDoc(sel.typeId);
    else if (sel.kind === "tab") clearTabDoc(sel.key);
    draft = defaultBody;
  }
  function addPage(e: Event): void {
    e.stopPropagation();
    open.pages = true;
    select({ kind: "page", id: createPage().id });
  }
  async function removePage(id: string, e: MouseEvent): Promise<void> {
    e.stopPropagation();
    if (!(await confirmAction("Usunąć stronę?", "Tej operacji nie można cofnąć.", { confirmText: "Usuń", danger: true }))) return;
    deletePage(id);
    if (sel.kind === "page" && sel.id === id) select({ kind: "tab", key: TAB_DOCS[0].key });
  }

  // reorder own pages by dragging the grip (pointer events — HTML5 DnD is unreliable in webviews)
  let dragFrom = $state<number | null>(null);
  let dragOver = $state<number | null>(null);
  function gripDown(e: PointerEvent, i: number): void {
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragFrom = dragOver = i;
  }
  function gripMove(e: PointerEvent): void {
    if (dragFrom === null) return;
    const row = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest<HTMLElement>("[data-page]");
    if (row) dragOver = Number(row.dataset.page);
  }
  function gripUp(): void {
    if (dragFrom !== null && dragOver !== null) movePage(dragFrom, dragOver);
    dragFrom = dragOver = null;
  }

  const fmtDefault = (v: unknown) => (typeof v === "boolean" ? (v ? "tak" : "nie") : Array.isArray(v) ? "—" : String(v ?? ""));
</script>

{#snippet chevron(on: boolean)}
  <svg class="chev" class:on width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l5 5-5 5" /></svg>
{/snippet}

<div class="docs">
  <div class="top">
    <span class="hint">{edit ? "Tryb edycji — każda sekcja to Markdown, zapis automatyczny" : "Poradnik i opis działania praTRD"}</span>
    <button class="btn" class:primary={edit} onclick={() => ((edit = !edit), reset(sel))}>
      <Icon name={edit ? "check" : "edit"} size={12} />
      {edit ? "Gotowe" : "Edytuj"}
    </button>
  </div>
  <div class="layout">
    <nav class="nav">
      <div class="group">
        <button class="ghead pages" onclick={() => (open.pages = !open.pages)}>
          {@render chevron(open.pages)}<Icon name="book" size={13} /><span>Poradniki</span>
          {#if edit}
            <span class="add" role="button" tabindex="0" title="Nowa strona" onclick={addPage} onkeydown={(e) => e.key === "Enter" && addPage(e)}>+</span>
          {/if}
        </button>
        {#if open.pages}
          <div class="gbody" role="list" onpointermove={gripMove} onpointerup={gripUp}>
            {#each pages as p, i (p.id)}
              <div class="prow" class:drag={dragFrom === i} class:over={dragOver === i && dragFrom !== null && dragFrom !== i} data-page={i} role="listitem">
                {#if edit}
                  <span class="grip" role="button" tabindex="-1" title="Przeciągnij, aby zmienić kolejność" onpointerdown={(e) => gripDown(e, i)}>⋮⋮</span>
                {/if}
                <button class="item" class:on={sel.kind === "page" && sel.id === p.id} onclick={() => select({ kind: "page", id: p.id })}>
                  {p.title || "(bez tytułu)"}
                </button>
                {#if edit}<button class="del" title="Usuń stronę" onclick={(e) => removePage(p.id, e)}>✕</button>{/if}
              </div>
            {/each}
            {#if !pages.length}<div class="empty">{edit ? "Kliknij +, aby dodać stronę" : "Brak własnych stron"}</div>{/if}
          </div>
        {/if}
      </div>

      <div class="group">
        <button class="ghead tabs" onclick={() => (open.tabs = !open.tabs)}>
          {@render chevron(open.tabs)}<Icon name="layers" size={13} /><span>Aplikacja</span>
        </button>
        {#if open.tabs}
          <div class="gbody">
            {#each TAB_DOCS as t (t.key)}
              <button class="item" class:on={sel.kind === "tab" && sel.key === t.key} onclick={() => select({ kind: "tab", key: t.key })}>{t.title}</button>
            {/each}
          </div>
        {/if}
      </div>

      <div class="group">
        <button class="ghead nodes" onclick={() => (open.nodes = !open.nodes)}>
          {@render chevron(open.nodes)}<Icon name="cube" size={13} /><span>Node'y</span>
        </button>
        {#if open.nodes}
          <div class="gbody scroll">
            {#each grouped as g (g.domain)}
              <div class="dom" style:color={DOMAIN_COLOR[g.domain]}>{g.label}</div>
              {#each g.stages as s (s.stage)}
                <div class="stage">{STAGES[s.stage]}</div>
                {#each s.items as t (t.id)}
                  <button class="item node" class:on={sel.kind === "node" && sel.typeId === t.id} onclick={() => select({ kind: "node", typeId: t.id })}>
                    <i style:background={DOMAIN_COLOR[t.domain]}></i>{t.label}
                    {#if hasNodeDoc(t.id)}<small title="Opis zmieniony">✎</small>{/if}
                  </button>
                {/each}
              {/each}
            {/each}
          </div>
        {/if}
      </div>
    </nav>

    <article class="main">
      <header>
        {#if edit && sel.kind === "page"}
          <input class="ttl" bind:value={draftTitle} oninput={() => sel.kind === "page" && updatePage(sel.id, { title: draftTitle })} placeholder="Tytuł strony…" />
        {:else}
          <h2 style:color={nodeDef ? DOMAIN_COLOR[nodeDef.domain] : null}>{title}</h2>
        {/if}
        {#if nodeDef}<span class="sub">{domainLabels()[nodeDef.domain]} · {STAGES[nodeDef.stage]}</span>{/if}
        {#if edit && overridden}
          <button class="btn" onclick={restore}><Icon name="undo" size={12} /> Przywróć domyślny</button>
        {/if}
      </header>

      <div class="body">
        {#if nodeDef}
          <!-- the node at a glance, straight from its schema -->
          <div class="flow">
            <div class="ports">
              {#each nodeDef.inputs as p (p.id)}
                <span class="port" style:--c={PORT_COLORS[p.kind]} title={PORT_LABELS[p.kind]}><i></i>{p.label}{#if p.optional}<small> (opcj.)</small>{/if}</span>
              {/each}
              {#if !nodeDef.inputs.length}<span class="none">źródło</span>{/if}
            </div>
            <div class="card" style:border-color={DOMAIN_COLOR[nodeDef.domain]}>{nodeDef.label}</div>
            <div class="ports">
              {#each nodeDef.outputs as p (p.id)}
                <span class="port" style:--c={PORT_COLORS[p.kind]} title={PORT_LABELS[p.kind]}><i></i>{p.label}</span>
              {/each}
            </div>
          </div>
          {#if nodeDef.params.some((p) => !HIDDEN_PARAMS.includes(p.type))}
            <table class="params">
              <tbody>
                {#each nodeDef.params.filter((p) => !HIDDEN_PARAMS.includes(p.type)) as p (p.key)}
                  <tr>
                    <td>{p.label}</td>
                    <td class="dim">
                      {#if p.type === "select"}{p.options.map((o) => o.label).join(" · ")}{:else if p.min !== null && p.max !== null}{p.min} – {p.max}{p.unit ? ` ${p.unit}` : ""}{:else}{p.unit}{/if}
                    </td>
                    <td class="def">{p.type === "select" ? (p.options.find((o) => o.value === p.default)?.label ?? "") : fmtDefault(p.default)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        {/if}
        {#if edit}
          <textarea class="editor" bind:value={draft} oninput={onDraft} placeholder="Markdown: # nagłówek, **pogrubienie**, - lista, `kod`"></textarea>
        {:else if html}
          <div class="md">{@html html}</div>
        {:else}
          <p class="empty">Brak opisu — „Edytuj”, aby go dodać.</p>
        {/if}
      </div>
    </article>
  </div>
</div>

<style>
  .docs {
    flex: 1;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .top {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 9px 18px;
    border-bottom: 1px solid var(--line-1);
  }
  .hint {
    font-size: 0.68rem;
    color: var(--text-dim-3);
  }
  .layout {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .nav {
    width: 260px;
    flex-shrink: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border-right: 1px solid var(--line-1);
  }
  .group {
    flex-shrink: 0;
    border: 1px solid var(--line-1);
    border-radius: 10px;
    overflow: hidden;
  }
  .ghead {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 10px;
    font: inherit;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    text-align: left;
    border: 0;
    cursor: pointer;
  }
  .ghead span:not(.add) {
    flex: 1;
  }
  .ghead.pages {
    color: var(--port-segment);
    background: rgba(123, 196, 127, 0.12);
  }
  .ghead.tabs {
    color: var(--port-wolumen);
    background: rgba(91, 155, 213, 0.12);
  }
  .ghead.nodes {
    color: var(--port-punkty);
    background: rgba(242, 153, 74, 0.12);
  }
  .chev {
    transition: transform var(--t-fast);
  }
  .chev.on {
    transform: rotate(90deg);
  }
  .add {
    width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 5px;
  }
  .gbody {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 5px;
  }
  .gbody.scroll {
    max-height: 46vh;
    overflow-y: auto;
  }
  .item {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 8px;
    font: inherit;
    font-size: 0.72rem;
    text-align: left;
    color: var(--text-dim-1);
    background: none;
    border: 1px solid transparent;
    border-radius: 6px;
    cursor: pointer;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .item:hover {
    color: var(--text-strong);
    background: var(--hover);
  }
  .item.on {
    color: var(--accent);
    background: var(--accent-a15);
    border-color: var(--accent-a30);
  }
  .item.node {
    padding-left: 14px;
    font-size: 0.68rem;
  }
  .item i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .item small {
    margin-left: auto;
    color: var(--text-dim-3);
  }
  .dom {
    padding: 7px 6px 2px;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .stage {
    padding: 2px 6px 1px 12px;
    font-size: 0.58rem;
    color: var(--text-dim-4);
  }
  .prow {
    display: flex;
    align-items: center;
    border-radius: 6px;
  }
  .prow.drag {
    opacity: 0.4;
  }
  .prow.over {
    outline: 1px dashed var(--accent-a40);
    background: var(--accent-a10);
  }
  .grip {
    padding: 0 4px;
    font-size: 0.7rem;
    color: var(--text-dim-3);
    cursor: grab;
    touch-action: none;
  }
  .del {
    padding: 2px 6px;
    font-size: 0.7rem;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .del:hover {
    color: var(--danger);
  }
  .empty {
    padding: 6px 8px;
    font-size: 0.66rem;
    font-style: italic;
    color: var(--text-dim-3);
  }
  .main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  header {
    flex-shrink: 0;
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 16px 26px 12px;
    border-bottom: 1px solid var(--line-1);
  }
  h2 {
    font-size: 1.1rem;
    color: var(--text-strong);
  }
  .sub {
    flex: 1;
    font-size: 0.68rem;
    color: var(--text-dim-3);
  }
  .ttl {
    flex: 1;
    max-width: 420px;
    padding: 4px 10px;
    font: inherit;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text-strong);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 7px;
    outline: none;
  }
  .body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 18px 26px 30px;
  }
  .flow {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px;
    background: var(--bg-deep);
    border-radius: 10px;
  }
  .ports {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .ports:last-child {
    align-items: flex-start;
  }
  .ports:first-child {
    align-items: flex-end;
  }
  .port {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.7rem;
    color: var(--text-dim-1);
  }
  .port i {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--c);
    box-shadow: 0 0 6px var(--c);
  }
  .ports:first-child .port {
    flex-direction: row-reverse;
  }
  .port small {
    color: var(--text-dim-4);
  }
  .none {
    font-size: 0.66rem;
    color: var(--text-dim-4);
  }
  .card {
    padding: 12px 18px;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--text-strong);
    background: var(--bg-panel);
    border: 1px solid;
    border-top-width: 3px;
    border-radius: 8px;
  }
  .params {
    border-collapse: collapse;
    font-size: 0.72rem;
  }
  .params td {
    padding: 4px 14px 4px 0;
    border-bottom: 1px solid var(--line-1);
    color: var(--text);
  }
  .params .dim {
    color: var(--text-dim-2);
  }
  .params .def {
    color: var(--accent);
  }
  .editor {
    flex: 1;
    min-height: 300px;
    resize: vertical;
    padding: 14px;
    font: inherit;
    font-size: 0.78rem;
    line-height: 1.7;
    color: var(--text);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: 10px;
    outline: none;
  }
  .editor:focus {
    border-color: var(--accent-a30);
  }
  .md {
    max-width: 860px;
    font-size: 0.8rem;
    line-height: 1.68;
    color: rgba(255, 255, 255, 0.78);
  }
  .md :global(h1) {
    margin: 1.2em 0 0.6em;
    padding-bottom: 6px;
    font-size: 1rem;
    color: var(--accent);
    border-bottom: 1px solid var(--accent-a25);
  }
  .md :global(h2) {
    margin: 1.1em 0 0.5em;
    padding-bottom: 4px;
    font-size: 0.9rem;
    color: var(--text-strong);
    border-bottom: 1px solid var(--line-2);
  }
  .md :global(h3) {
    margin: 1em 0 0.4em;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-dim-1);
  }
  .md :global(:is(h1, h2, h3):first-child) {
    margin-top: 0;
  }
  .md :global(p) {
    margin: 0 0 0.85em;
  }
  .md :global(strong) {
    color: var(--accent);
  }
  .md :global(:is(ul, ol)) {
    margin: 0 0 0.85em 1.2em;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .md :global(li::marker) {
    color: var(--accent);
    font-weight: 700;
  }
  .md :global(code) {
    padding: 0.1em 0.4em;
    font-size: 0.85em;
    color: var(--accent);
    background: var(--accent-a10);
    border-radius: 4px;
  }
  .md :global(pre) {
    margin: 0 0 0.85em;
    padding: 10px 14px;
    overflow-x: auto;
    background: var(--bg-deep);
    border-top: 2px solid var(--accent-a40);
    border-radius: 0 0 8px 8px;
  }
  .md :global(pre code) {
    padding: 0;
    color: var(--text);
    background: none;
  }
  .md :global(blockquote) {
    margin: 0 0 0.85em;
    padding: 6px 14px;
    color: var(--text-dim-1);
    background: var(--accent-a10);
    border-left: 3px solid var(--accent-a40);
    border-radius: 0 6px 6px 0;
  }
  .md :global(a) {
    color: var(--accent);
  }
  .md :global(table) {
    margin: 0 0 0.85em;
    border-collapse: collapse;
  }
  .md :global(:is(th, td)) {
    padding: 5px 10px;
    border: 1px solid var(--accent-a15);
  }
</style>
