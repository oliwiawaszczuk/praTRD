<script lang="ts">
  import { getSetting, setSetting } from "#lib/core/appSettings.svelte.ts";

  const GPU = [
    { v: 32 << 20, label: "32 M", mem: "64 MB" },
    { v: 128 << 20, label: "128 M", mem: "256 MB" },
    { v: 256 << 20, label: "256 M", mem: "512 MB" },
    { v: 512 << 20, label: "512 M", mem: "1 GB" },
  ];
  const CACHE = [
    { v: 5 << 30, label: "5 GB" },
    { v: 20 << 30, label: "20 GB" },
    { v: 50 << 30, label: "50 GB" },
    { v: 200 << 30, label: "200 GB" },
  ];
  const gpu = $derived(getSetting("gpu3dVoxels", 256 << 20));
  const cache = $derived(getSetting("cacheBytes", 20 << 30));
</script>

<div class="row" title="Ile wokseli może trafić do GPU w widoku 3D — więcej = pełniejsza rozdzielczość 3D">
  <span class="k">3D na GPU</span>
  <div class="segs">
    {#each GPU as g, n (g.v)}
      <button class="seg" class:active={gpu === g.v} onclick={() => setSetting("gpu3dVoxels", g.v)}>
        <span class="bars">{#each Array(n + 1) as _, i (i)}<i></i>{/each}</span>
        {g.label}<small>{g.mem}</small>
      </button>
    {/each}
  </div>
</div>
<div class="row" title="Ile miejsca na dysku mogą zająć wyniki node'ów (najstarsze są usuwane)">
  <span class="k">Cache grafu</span>
  <div class="segs">
    {#each CACHE as c (c.v)}
      <button class="seg" class:active={cache === c.v} onclick={() => setSetting("cacheBytes", c.v)}>{c.label}</button>
    {/each}
  </div>
</div>

<style>
  .row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .k {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
  .segs {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 5px;
  }
  .seg {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    padding: 6px 4px;
    font-size: var(--fs-xs);
    font-weight: 600;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    color: var(--text-dim-2);
    cursor: pointer;
  }
  .seg small {
    font-size: 0.56rem;
    font-weight: 400;
    color: var(--text-dim-4);
  }
  .seg.active {
    color: var(--accent);
    border-color: var(--accent-a40);
    background: var(--accent-a10);
  }
  .bars {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 12px;
  }
  .bars i {
    width: 4px;
    background: currentColor;
    border-radius: 1px;
    opacity: 0.7;
  }
  .bars i:nth-child(1) { height: 4px; }
  .bars i:nth-child(2) { height: 7px; }
  .bars i:nth-child(3) { height: 10px; }
  .bars i:nth-child(4) { height: 12px; }
</style>
