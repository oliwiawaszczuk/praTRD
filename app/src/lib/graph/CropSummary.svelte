<script lang="ts">
  // Card widget of "Przytnij": isometric sketch of the whole volume (grey) and the crop box
  // (gold). Click → 3-D box editor.
  import { boxFromParams, openCrop } from "./cropModal.svelte.ts";
  import type { GNode } from "./types.ts";

  let { node }: { node: GNode } = $props();
  const box = $derived(boxFromParams(node.params));
  const full = $derived(box.i[0] === 0 && box.i[1] === 1 && box.j[0] === 0 && box.j[1] === 1 && box.k[0] === 0 && box.k[1] === 1);

  // isometric: i → right-down, j → left-down, k → up
  const S = 34;
  const iso = (i: number, j: number, k: number): [number, number] => [
    60 + (i - j) * S * 0.87,
    44 + (i + j) * S * 0.5 - k * S,
  ];
  function edges(b: { i: [number, number]; j: [number, number]; k: [number, number] }): string {
    const c = (a: 0 | 1, bb: 0 | 1, cc: 0 | 1) => iso(b.i[a], b.j[bb], b.k[cc]);
    const segs: [[number, number], [number, number]][] = [];
    for (const a of [0, 1] as const) for (const bb of [0, 1] as const) segs.push([c(a, bb, 0), c(a, bb, 1)]);
    for (const a of [0, 1] as const) for (const cc of [0, 1] as const) segs.push([c(a, 0, cc), c(a, 1, cc)]);
    for (const bb of [0, 1] as const) for (const cc of [0, 1] as const) segs.push([c(0, bb, cc), c(1, bb, cc)]);
    return segs.map(([p, q]) => `M${p[0].toFixed(1)},${p[1].toFixed(1)}L${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("");
  }
</script>

<button class="crop" onpointerdown={(e) => e.stopPropagation()} onclick={() => openCrop(node.id)} title="Ustaw box przycięcia w 3D">
  <svg width="120" height="84" viewBox="0 0 120 84">
    <path d={edges({ i: [0, 1], j: [0, 1], k: [0, 1] })} class="vol" />
    <path d={edges(box)} class="box" />
  </svg>
  <span class="lbl">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2v14a2 2 0 0 0 2 2h14M18 22V8a2 2 0 0 0-2-2H2" /></svg>
    {full ? "Ustaw box" : "Edytuj box"}
  </span>
</button>

<style>
  .crop {
    width: calc(100% - 20px);
    margin: 4px 10px 8px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px 4px 2px;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 6px;
    cursor: pointer;
  }
  .crop:hover {
    border-color: var(--accent-a40);
  }
  .vol {
    fill: none;
    stroke: rgba(255, 255, 255, 0.22);
    stroke-width: 1;
  }
  .box {
    fill: none;
    stroke: var(--accent);
    stroke-width: 1.6;
  }
  .lbl {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    font-size: 0.6rem;
    color: var(--accent);
  }
</style>
