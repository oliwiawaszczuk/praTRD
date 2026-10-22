<script lang="ts">
  import Icon from "#lib/ui/Icon.svelte";
  import { DOMAIN_COLOR, domainLabels, nodeTypes } from "./registry.svelte.ts";
  import type { NodeTypeSchema, PortKind } from "./types.ts";

  let {
    x,
    y,
    bounds,
    accept,
    onpick,
    onclose,
  }: {
    x: number; // position inside the editor (CSS px)
    y: number;
    bounds: { w: number; h: number };
    /** only types with a socket of this kind on this side (connection dragged into empty space) */
    accept: { side: "in" | "out"; kind: PortKind } | null;
    onpick: (t: NodeTypeSchema) => void;
    onclose: () => void;
  } = $props();

  let query = $state("");
  let active = $state(0);
  let menu = $state<HTMLDivElement>();
  let input = $state<HTMLInputElement>();
  let pos = $state({ left: 0, top: 0 });

  const list = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return nodeTypes().filter((t) => {
      if (accept) {
        const ports = accept.side === "in" ? t.inputs : t.outputs;
        if (!ports.some((p) => p.kind === accept.kind)) return false;
      }
      return !q || t.label.toLowerCase().includes(q) || t.id.includes(q) || t.description.toLowerCase().includes(q);
    });
  });

  // keep inside the editor: flip to the other side of the anchor when it would overflow
  $effect(() => {
    void list.length;
    pos = { left: x, top: y };
    if (!menu) return;
    const r = menu.getBoundingClientRect();
    pos = {
      left: x + r.width > bounds.w ? Math.max(4, x - r.width) : x,
      top: y + r.height > bounds.h ? Math.max(4, y - r.height) : y,
    };
  });

  $effect(() => {
    input?.focus();
  });

  $effect(() => {
    void query;
    active = 0;
  });

  function onKey(e: KeyboardEvent): void {
    e.stopPropagation();
    if (e.key === "Escape") onclose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      active = Math.min(list.length - 1, active + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      active = Math.max(0, active - 1);
    } else if (e.key === "Enter" && list[active]) onpick(list[active]);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="menu"
  bind:this={menu}
  style:left="{pos.left}px"
  style:top="{pos.top}px"
  onpointerdown={(e) => e.stopPropagation()}
  onwheel={(e) => e.stopPropagation()}
>
  <div class="search">
    <Icon name="search" size={12} />
    <input bind:this={input} bind:value={query} placeholder="Szukaj node'a…" onkeydown={onKey} spellcheck="false" />
  </div>
  <ul>
    {#each list as t, n (t.id)}
      <li>
        <button class:active={n === active} onpointerenter={() => (active = n)} onclick={() => onpick(t)}>
          <i style:background={DOMAIN_COLOR[t.domain]}></i>
          <span class="l">{t.label}</span>
          <span class="d">{domainLabels()[t.domain] ?? t.domain}</span>
        </button>
      </li>
    {:else}
      <li class="none">Brak pasujących node'ów</li>
    {/each}
  </ul>
</div>

<style>
  .menu {
    position: absolute;
    z-index: 50;
    width: 260px;
    max-height: 320px;
    display: flex;
    flex-direction: column;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }
  .search {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 8px 10px;
    color: var(--text-dim-3);
    border-bottom: 1px solid var(--line-1);
  }
  input {
    flex: 1;
    background: none;
    border: none;
    outline: none;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  ul {
    list-style: none;
    overflow-y: auto;
    padding: 4px;
  }
  button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    text-align: left;
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text-dim-1);
  }
  button.active {
    background: var(--accent-a10);
    color: var(--accent);
  }
  i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .l {
    flex: 1;
  }
  .d {
    font-size: 0.6rem;
    color: var(--text-dim-4);
  }
  .none {
    padding: 10px;
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
</style>
