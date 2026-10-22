<script lang="ts">
  // One parameter widget, generated from the node-type schema.
  import { libraryVolumes } from "#lib/core/library.svelte.ts";
  import type { ParamSchema } from "./types.ts";

  let { p, value, onchange }: { p: ParamSchema; value: unknown; onchange: (v: unknown) => void } = $props();

  const num = $derived(Number(value ?? p.default));
  const decimals = $derived(p.type === "int" ? 0 : Math.max(0, -Math.floor(Math.log10(p.step || 0.1))));
  const stop = (e: Event) => e.stopPropagation();
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="field" onpointerdown={stop} onwheel={stop} title={p.help || undefined}>
  <span class="label">{p.label}</span>
  {#if p.type === "number" || p.type === "int"}
    <input
      class="slider"
      type="range"
      min={p.min ?? 0}
      max={p.max ?? 100}
      step={p.step ?? (p.type === "int" ? 1 : 0.1)}
      value={num}
      oninput={(e) => onchange(Number(e.currentTarget.value))}
    />
    <input
      class="num"
      type="number"
      min={p.min ?? undefined}
      max={p.max ?? undefined}
      step={p.step ?? undefined}
      value={num.toFixed(decimals)}
      onchange={(e) => onchange(Number(e.currentTarget.value))}
    />
    {#if p.unit}<span class="unit">{p.unit}</span>{/if}
  {:else if p.type === "select"}
    {#if p.options.length <= 3 && p.options.every((o) => o.label.length <= 8)}
      <div class="segs">
        {#each p.options as o (o.value)}
          <button class="seg" class:active={value === o.value} onclick={() => onchange(o.value)}>{o.label}</button>
        {/each}
      </div>
    {:else}
      <select class="sel" value={value} onchange={(e) => onchange(e.currentTarget.value)}>
        {#each p.options as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
      </select>
    {/if}
  {:else if p.type === "bool"}
    <input type="checkbox" checked={Boolean(value)} onchange={(e) => onchange(e.currentTarget.checked)} />
  {:else if p.type === "volume"}
    <select class="sel" value={value ?? ""} onchange={(e) => onchange(e.currentTarget.value)}>
      <option value="" disabled>— wybierz serię —</option>
      {#each libraryVolumes() as v (v.id)}<option value={v.id}>{v.name}</option>{/each}
    </select>
  {/if}
</div>

<style>
  .field {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 10px;
    font-size: 0.66rem;
  }
  .label {
    width: 62px;
    flex-shrink: 0;
    color: var(--text-dim-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .slider {
    flex: 1;
    min-width: 0;
    accent-color: var(--accent);
    height: 14px;
  }
  .num {
    width: 46px;
    padding: 2px 4px;
    font-size: 0.64rem;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 4px;
    color: var(--text);
    text-align: right;
  }
  .num::-webkit-inner-spin-button {
    display: none;
  }
  .unit {
    width: 16px;
    color: var(--text-dim-4);
  }
  .sel {
    flex: 1;
    min-width: 0;
    padding: 3px 6px;
    font-size: 0.64rem;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 4px;
    color: var(--text);
  }
  .segs {
    flex: 1;
    display: flex;
    gap: 2px;
  }
  .seg {
    flex: 1;
    padding: 3px 4px;
    font-size: 0.62rem;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 4px;
    color: var(--text-dim-3);
    cursor: pointer;
  }
  .seg.active {
    color: var(--accent);
    border-color: var(--accent-a30);
    background: var(--accent-a10);
  }
  input[type="checkbox"] {
    accent-color: var(--accent);
  }
</style>
