<script lang="ts">
  import { nodeDoc } from "#lib/tabs/dokumentacja/appdocs.svelte.ts";
  import { DOMAIN_COLOR, domainLabels, nodeTypes } from "./registry.svelte.ts";
  import type { NodeTypeSchema } from "./types.ts";

  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";

  let { ondrop }: { ondrop: (typeId: string, x: number, y: number) => void } = $props();

  // fixed bar; only its width changes, by dragging the right edge
  const MIN_W = 130;
  const MAX_W = 360;
  let width = $state(wsGet<number>("graph_paletteWidth", 170));
  let resizing: { x0: number; w0: number } | null = null;
  function onEdgeDown(e: PointerEvent): void {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    resizing = { x0: e.clientX, w0: width };
  }
  function onEdgeMove(e: PointerEvent): void {
    if (resizing) width = Math.min(MAX_W, Math.max(MIN_W, resizing.w0 + e.clientX - resizing.x0));
  }
  function onEdgeUp(): void {
    if (!resizing) return;
    resizing = null;
    wsSet("graph_paletteWidth", Math.round(width));
  }

  const STAGES: Record<string, string> = { dane: "Dane", przetwarzanie: "Przetwarzanie", wynik: "Wynik" };

  const groups = $derived.by(() => {
    const out: { domain: string; items: NodeTypeSchema[] }[] = [];
    for (const t of nodeTypes()) {
      let g = out.find((x) => x.domain === t.domain);
      if (!g) out.push((g = { domain: t.domain, items: [] }));
      g.items.push(t);
    }
    const order = ["dane", "przetwarzanie", "wynik"];
    for (const g of out) g.items.sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage));
    return out;
  });

  let ghost = $state<{ t: NodeTypeSchema; x: number; y: number } | null>(null);

  function onDown(e: PointerEvent, t: NodeTypeSchema): void {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    ghost = { t, x: e.clientX, y: e.clientY };
  }
  function onMove(e: PointerEvent): void {
    if (ghost) ghost = { ...ghost, x: e.clientX, y: e.clientY };
  }
  function onUp(e: PointerEvent): void {
    if (ghost) ondrop(ghost.t.id, e.clientX, e.clientY);
    ghost = null;
  }
</script>

<aside style:width="{width}px">
    <div class="list">
      {#each groups as g (g.domain)}
        <h5 style:color={DOMAIN_COLOR[g.domain]}>{domainLabels()[g.domain] ?? g.domain}</h5>
        {#each g.items as t (t.id)}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="item"
            title={nodeDoc(t.id, t.description)}
            onpointerdown={(e) => onDown(e, t)}
            onpointermove={onMove}
            onpointerup={onUp}
            onpointercancel={() => (ghost = null)}
          >
            <i style:background={DOMAIN_COLOR[t.domain]}></i>
            <span>{t.label}</span>
            <small>{STAGES[t.stage]}</small>
          </div>
        {/each}
      {/each}
    </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="edge"
    title="Przeciągnij, aby zmienić szerokość"
    onpointerdown={onEdgeDown}
    onpointermove={onEdgeMove}
    onpointerup={onEdgeUp}
    onpointercancel={onEdgeUp}
  ></div>
</aside>

{#if ghost}
  <div class="ghost" style:left="{ghost.x + 10}px" style:top="{ghost.y + 6}px">{ghost.t.label}</div>
{/if}

<style>
  aside {
    position: relative;
    flex-shrink: 0;
    background: var(--bg-panel-2);
    border-right: 1px solid var(--line-1);
  }
  .edge {
    position: absolute;
    top: 0;
    right: -3px;
    bottom: 0;
    width: 7px;
    z-index: 3;
    cursor: col-resize;
    touch-action: none;
  }
  .edge:hover,
  .edge:active {
    background: var(--accent-a30);
  }
  .list {
    height: 100%;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  h5 {
    margin: 6px 0 2px;
    font-size: 0.6rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 7px;
    font-size: var(--fs-xs);
    color: var(--text-dim-1);
    border-radius: var(--radius-sm);
    cursor: grab;
    -webkit-user-select: none;
    user-select: none;
    touch-action: none;
  }
  .item:hover {
    background: var(--hover);
    color: var(--text);
  }
  .item i {
    width: 7px;
    height: 7px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .item span {
    flex: 1;
  }
  small {
    font-size: 0.56rem;
    color: var(--text-dim-4);
  }
  .ghost {
    position: fixed;
    z-index: 1000;
    padding: 5px 10px;
    font-size: var(--fs-xs);
    color: var(--accent);
    background: var(--bg-panel);
    border: 1px solid var(--accent-a40);
    border-radius: var(--radius-sm);
    pointer-events: none;
  }
</style>
