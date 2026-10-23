<script lang="ts">
  import { nodeDoc } from "#lib/tabs/dokumentacja/appdocs.svelte.ts";
  import { DOMAIN_COLOR, domainLabels, nodeTypes } from "./registry.svelte.ts";
  import type { NodeTypeSchema } from "./types.ts";

  let { open = $bindable(true), ondrop }: { open?: boolean; ondrop: (typeId: string, x: number, y: number) => void } =
    $props();

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

<aside class:open>
  <button class="toggle" title={open ? "Zwiń listę" : "Lista node'ów"} onclick={() => (open = !open)}>
    {open ? "‹" : "›"}
  </button>
  {#if open}
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
  {/if}
</aside>

{#if ghost}
  <div class="ghost" style:left="{ghost.x + 10}px" style:top="{ghost.y + 6}px">{ghost.t.label}</div>
{/if}

<style>
  aside {
    position: relative;
    width: 14px;
    flex-shrink: 0;
    background: var(--bg-panel-2);
    border-right: 1px solid var(--line-1);
    transition: width 0.18s ease;
  }
  aside.open {
    width: 170px;
  }
  .toggle {
    position: absolute;
    right: -1px;
    top: 50%;
    transform: translateY(-50%);
    z-index: 3;
    width: 14px;
    height: 34px;
    padding: 0;
    font-size: 0.7rem;
    color: var(--text-dim-3);
    background: var(--bg-panel);
    border: 1px solid var(--line-1);
    border-radius: 4px 0 0 4px;
    cursor: pointer;
  }
  .list {
    height: 100%;
    overflow-y: auto;
    padding: 10px 18px 10px 10px;
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
