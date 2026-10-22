<script lang="ts">
  // Markups in the 3-D view: projected through the camera (SVG, re-projected per camera
  // change), always on top so a ruler inside a vessel stays visible. ROI = wireframe box.
  import { untrack } from "svelte";
  import { shownItems } from "./markupDraft.svelte.ts";
  import { MARKUP_COLOR, measureText, roiBox } from "./markups.ts";
  import type { Vec3 } from "./geometry.ts";
  import type { SliceLayers } from "./layers.ts";
  import type { VolumeRenderer3D } from "./VolumeRenderer3D.ts";

  let { renderer, layers }: { renderer: VolumeRenderer3D | null; layers: SliceLayers } = $props();

  let tick = $state(0);
  $effect(() => {
    const r = renderer;
    if (!r) return;
    let raf = 0;
    const off = r.onCamera(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => tick++);
    });
    untrack(() => tick++);
    return () => {
      off();
      cancelAnimationFrame(raf);
    };
  });

  // ROI box edges as corner-index pairs (corner n: bit 0 → x, bit 1 → y, bit 2 → z)
  const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];

  const shapes = $derived.by(() => {
    void tick;
    const r = renderer;
    if (!r) return [];
    const out: { key: string; pts: [number, number][]; lines: string[]; label: [number, number, string]; focus: boolean; point: boolean }[] = [];
    for (const g of layers.markups) {
      for (const { m, draft } of shownItems(g.nodeId, g.items)) {
        const focus = draft || layers.focusMarkup === m.id;
        if (m.type === "roi") {
          const { lo, hi } = roiBox(m);
          const c = Array.from({ length: 8 }, (_, n) =>
            r.project([(n & 1 ? hi : lo)[0], (n & 2 ? hi : lo)[1], (n & 4 ? hi : lo)[2]] as Vec3),
          );
          const top = c.reduce((a, b) => (b[1] < a[1] ? b : a));
          out.push({
            key: `${g.nodeId}:${m.id}`,
            pts: [],
            lines: EDGES.map(([a, b]) => `M${c[a][0]},${c[a][1]}L${c[b][0]},${c[b][1]}`),
            label: [top[0], top[1] - 8, measureText(m)],
            focus,
            point: false,
          });
          continue;
        }
        const pts = m.p.map((p) => r.project(p));
        const at = m.type === "angle" ? pts[1] : m.type === "line" ? [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2] : pts[0];
        out.push({
          key: `${g.nodeId}:${m.id}`,
          pts,
          lines: pts.length > 1 ? [`M${pts.map((p) => `${p[0]},${p[1]}`).join("L")}`] : [],
          label: [at[0] + 9, at[1] - 9, m.type === "point" ? m.name : measureText(m)],
          focus,
          point: m.type === "point",
        });
      }
    }
    return out;
  });
</script>

{#if shapes.length}
  <svg class="mk3" aria-hidden="true" style:--c={MARKUP_COLOR}>
    {#each shapes as s (s.key)}
      <g class:focus={s.focus}>
        {#each s.lines as d, n (n)}<path {d} class="ln" />{/each}
        {#each s.pts as p, n (n)}<circle cx={p[0]} cy={p[1]} r={s.point ? 5 : 3.5} class="pt" />{/each}
        {#if s.label[2]}<text x={s.label[0]} y={s.label[1]} class="lbl">{s.label[2]}</text>{/if}
      </g>
    {/each}
  </svg>
{/if}

<style>
  .mk3 {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    color: var(--c);
  }
  .focus {
    color: #fff;
  }
  .ln {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
  }
  .pt {
    fill: #111;
    stroke: currentColor;
    stroke-width: 2;
  }
  .lbl {
    font-size: 11px;
    font-weight: 600;
    fill: currentColor;
    filter: drop-shadow(0 0 1.5px #000) drop-shadow(0 0 1px #000);
  }
</style>
