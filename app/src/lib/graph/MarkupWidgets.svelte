<script lang="ts">
  // Card editor of a "Markupy" node: four tools (point, ruler, angle, ROI box) used in the
  // views, and the list of placed markups with their live measurement. Hover → highlighted in
  // the views, click → all views jump to it, double click → rename, × → delete.
  import { promptText } from "#lib/ui/dialogs.svelte.ts";
  import { setCursor } from "#lib/viewport/scene.svelte.ts";
  import { centroid, measureText, type Markup, type MarkupType } from "#lib/viewport/markups.ts";
  import { segTools, setFocusMarkup, setTool } from "./segTools.svelte.ts";
  import { commit } from "./store.svelte.ts";
  import type { GNode } from "./types.ts";

  let { node }: { node: GNode } = $props();
  const stop = (e: Event) => e.stopPropagation();

  const TOOLS: { t: MarkupType; title: string; d: string }[] = [
    { t: "point", title: "Punkt — kliknij w widoku 2D lub na powierzchni 3D", d: "M12 12m-3.5 0a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0" },
    { t: "line", title: "Linijka — kliknij oba końce albo przeciągnij (2D i 3D)", d: "M4 18L18 4M7 15l2 2M10 12l2 2M13 9l2 2" },
    { t: "angle", title: "Kąt — trzy kliknięcia, wierzchołek jako drugi", d: "M5 19L12 5M5 19h14M9 19a5 5 0 0 0-1.3-3.6" },
    { t: "roi", title: "ROI — przeciągnij prostokąt w widoku 2D (głębokość: uchwyty w innym widoku)", d: "M5 5h14v14H5z" },
  ];
  const items = $derived((node.params.items as Markup[]) ?? []);
  const active = (t: MarkupType) => segTools.tool === t && segTools.nodeId === node.id;

  function toggle(t: MarkupType): void {
    setTool(active(t) ? null : t, node.id);
  }
  function remove(id: string): void {
    node.params.items = items.filter((m) => m.id !== id);
    setFocusMarkup(null);
    commit();
  }
  async function rename(m: Markup): Promise<void> {
    const name = await promptText("Nazwa markupu", { value: m.name, confirmText: "Zmień" });
    if (!name?.trim()) return;
    node.params.items = items.map((x) => (x.id === m.id ? { ...x, name: name.trim() } : x));
    commit();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="w" onpointerdown={stop} onwheel={stop}>
  <div class="tools">
    {#each TOOLS as b (b.t)}
      <button class="tb" class:on={active(b.t)} title={b.title} onclick={() => toggle(b.t)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d={b.d} stroke-dasharray={b.t === "roi" ? "3 2" : null} />
        </svg>
      </button>
    {/each}
  </div>
  {#if items.length}
    <ul class="list">
      {#each items as m (m.id)}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <li
          onpointerenter={() => setFocusMarkup(m.id)}
          onpointerleave={() => setFocusMarkup(null)}
          onclick={() => setCursor(centroid(m))}
          ondblclick={() => rename(m)}
          title="Kliknij: pokaż w widokach · dwuklik: zmień nazwę"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
            <path d={TOOLS.find((b) => b.t === m.type)?.d} />
          </svg>
          <span class="nm">{m.name}</span>
          {#if m.type !== "point"}<b>{measureText(m)}</b>{/if}
          <button class="x" title="Usuń" onclick={(e) => (e.stopPropagation(), remove(m.id))}>✕</button>
        </li>
      {/each}
    </ul>
  {:else}
    <div class="hint">wybierz narzędzie i kliknij w widoku</div>
  {/if}
</div>

<style>
  .w {
    margin: 4px 10px 6px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .tools {
    display: flex;
    gap: 4px;
  }
  .tb {
    flex: 1;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--port-punkty);
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 6px;
    cursor: pointer;
  }
  .tb:hover {
    border-color: var(--line-3);
  }
  .tb.on {
    color: #111;
    background: var(--port-punkty);
    border-color: var(--port-punkty);
    box-shadow: 0 0 10px rgba(242, 153, 74, 0.45);
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 132px;
    overflow-y: auto;
  }
  li {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 22px;
    padding: 0 4px;
    border-radius: 4px;
    font-size: 0.64rem;
    color: var(--port-punkty);
    cursor: pointer;
  }
  li:hover {
    background: var(--bg-deepest);
  }
  .nm {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--text-dim-1);
  }
  li b {
    font-weight: 700;
    color: var(--text);
    white-space: nowrap;
  }
  .x {
    width: 16px;
    padding: 0;
    font-size: 0.6rem;
    color: var(--text-dim-4);
    background: none;
    border: 0;
    cursor: pointer;
    visibility: hidden;
  }
  li:hover .x {
    visibility: visible;
  }
  .x:hover {
    color: var(--danger);
  }
  .hint {
    font-size: 0.6rem;
    color: var(--text-dim-4);
    text-align: center;
    padding: 4px;
  }
</style>
