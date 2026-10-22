<script lang="ts">
  // Window/level ON the histogram: the shaded band is the window; drag it to move the
  // level, drag its edges to change the width. The grey ramp under it shows the mapping.
  import type { WL } from "#lib/viewport/presets.ts";

  let {
    histogram,
    min,
    max,
    wl,
    onchange,
  }: { histogram: number[]; min: number; max: number; wl: WL; onchange: (wl: WL) => void } = $props();

  const W = 246;
  const H = 64;
  const span = $derived(Math.max(1e-9, max - min));
  const toX = (v: number) => ((v - min) / span) * W;
  const toV = (x: number) => min + (x / W) * span;

  // log scale: air/background bins would otherwise flatten everything else
  const path = $derived.by(() => {
    if (!histogram.length) return "";
    const logs = histogram.map((c) => Math.log1p(c));
    const top = Math.max(...logs) || 1;
    const step = W / histogram.length;
    let d = `M0,${H}`;
    logs.forEach((l, i) => (d += ` L${(i * step).toFixed(1)},${(H - (l / top) * (H - 4)).toFixed(1)}`));
    return d + ` L${W},${H} Z`;
  });

  const lo = $derived(Math.max(0, Math.min(W, toX(wl.center - wl.width / 2))));
  const hi = $derived(Math.max(0, Math.min(W, toX(wl.center + wl.width / 2))));

  const clipId = `wclip-${Math.random().toString(36).slice(2, 8)}`;
  let drag: { mode: "move" | "lo" | "hi"; x: number; wl: WL } | null = null;
  let svg = $state<SVGSVGElement>();

  function localX(e: PointerEvent): number {
    const r = svg!.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * W;
  }
  function down(e: PointerEvent, mode: "move" | "lo" | "hi"): void {
    e.stopPropagation();
    svg!.setPointerCapture(e.pointerId);
    drag = { mode, x: localX(e), wl: { ...wl } };
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    const dv = ((localX(e) - drag.x) / W) * span;
    const a = drag.wl.center - drag.wl.width / 2;
    const b = drag.wl.center + drag.wl.width / 2;
    if (drag.mode === "move") onchange({ center: drag.wl.center + dv, width: drag.wl.width });
    else if (drag.mode === "lo") {
      const na = Math.min(a + dv, b - 1);
      onchange({ center: (na + b) / 2, width: b - na });
    } else {
      const nb = Math.max(b + dv, a + 1);
      onchange({ center: (a + nb) / 2, width: nb - a });
    }
  }
  function bgDown(e: PointerEvent): void {
    // click outside the band → centre the window there
    const v = toV(localX(e));
    onchange({ center: v, width: wl.width });
    down(e, "move");
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  bind:this={svg}
  viewBox="0 0 {W} {H + 10}"
  class="hist"
  onpointerdown={bgDown}
  onpointermove={move}
  onpointerup={() => (drag = null)}
  onpointercancel={() => (drag = null)}
>
  <defs>
    <clipPath id={clipId}><rect x={lo} y="0" width={Math.max(0, hi - lo)} height={H} /></clipPath>
    <linearGradient id="{clipId}-ramp" x1="0" x2="1">
      <stop offset="0" stop-color="#000" />
      <stop offset="1" stop-color="#fff" />
    </linearGradient>
  </defs>
  <path d={path} class="area" />
  <rect x={lo} y="0" width={Math.max(1, hi - lo)} height={H} class="band" onpointerdown={(e) => down(e, "move")} />
  <path d={path} class="area in" clip-path="url(#{clipId})" />
  <line x1={lo} x2={lo} y1="0" y2={H} class="edge" />
  <line x1={hi} x2={hi} y1="0" y2={H} class="edge" />
  <rect x={lo - 5} y="0" width="10" height={H} class="grip" onpointerdown={(e) => down(e, "lo")} />
  <rect x={hi - 5} y="0" width="10" height={H} class="grip" onpointerdown={(e) => down(e, "hi")} />
  <!-- mapping: black below the window, ramp inside, white above -->
  <rect x="0" y={H + 3} width={lo} height="5" fill="#000" />
  <rect x={lo} y={H + 3} width={Math.max(1, hi - lo)} height="5" fill="url(#{clipId}-ramp)" />
  <rect x={hi} y={H + 3} width={W - hi} height="5" fill="#fff" />
</svg>

<style>
  .hist {
    width: 100%;
    display: block;
    cursor: crosshair;
    touch-action: none;
    background: var(--bg-deep);
    border-radius: var(--radius-sm);
  }
  .area {
    fill: rgba(255, 255, 255, 0.16);
  }
  .area.in {
    fill: var(--accent-a40);
    pointer-events: none;
  }
  .band {
    fill: var(--accent-a10);
    cursor: grab;
  }
  .edge {
    stroke: var(--accent);
    stroke-width: 1.5;
    pointer-events: none;
  }
  .grip {
    fill: transparent;
    cursor: ew-resize;
  }
</style>
