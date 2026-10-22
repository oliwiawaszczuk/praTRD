<script lang="ts">
  // Histogram (log) with a [lo, hi] band: drag an edge, or the band to move both.
  // Used by threshold-type nodes; values outside the band are dimmed.
  let {
    histogram,
    min,
    max,
    lo,
    hi,
    color = "#7bc47f",
    onchange,
  }: {
    histogram: number[];
    min: number;
    max: number;
    lo: number;
    hi: number;
    color?: string;
    onchange: (lo: number, hi: number) => void;
  } = $props();

  const W = 210;
  const H = 46;
  const span = $derived(Math.max(1e-9, max - min));
  const toX = (v: number) => Math.min(W, Math.max(0, ((v - min) / span) * W));
  const path = $derived.by(() => {
    if (!histogram.length) return "";
    const logs = histogram.map((c) => Math.log1p(c));
    const top = Math.max(...logs) || 1;
    const step = W / histogram.length;
    let d = `M0,${H}`;
    logs.forEach((l, i) => (d += ` L${(i * step).toFixed(1)},${(H - (l / top) * (H - 3)).toFixed(1)}`));
    return d + ` L${W},${H} Z`;
  });
  const x0 = $derived(toX(lo));
  const x1 = $derived(toX(hi));
  const id = `rh-${Math.random().toString(36).slice(2, 8)}`;

  let svg = $state<SVGSVGElement>();
  let drag: { mode: "lo" | "hi" | "band"; x: number; lo: number; hi: number } | null = null;
  const vx = (e: PointerEvent) => {
    const r = svg!.getBoundingClientRect();
    return ((e.clientX - r.left) / r.width) * W;
  };
  function down(e: PointerEvent, mode: "lo" | "hi" | "band"): void {
    e.stopPropagation();
    svg!.setPointerCapture(e.pointerId);
    drag = { mode, x: vx(e), lo, hi };
  }
  function bg(e: PointerEvent): void {
    const v = min + (vx(e) / W) * span;
    down(e, Math.abs(v - lo) < Math.abs(v - hi) ? "lo" : "hi");
    move(e);
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    const dv = ((vx(e) - drag.x) / W) * span;
    const r = (v: number) => Math.round(v);
    if (drag.mode === "lo") onchange(r(Math.min(drag.lo + dv, hi - 1)), hi);
    else if (drag.mode === "hi") onchange(lo, r(Math.max(drag.hi + dv, lo + 1)));
    else onchange(r(drag.lo + dv), r(drag.hi + dv));
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  bind:this={svg}
  class="rh"
  viewBox="0 0 {W} {H}"
  onpointerdown={bg}
  onpointermove={move}
  onpointerup={() => (drag = null)}
  onpointercancel={() => (drag = null)}
>
  <defs><clipPath id={id}><rect x={x0} y="0" width={Math.max(0, x1 - x0)} height={H} /></clipPath></defs>
  <path d={path} class="all" />
  <path d={path} fill={color} opacity="0.75" clip-path="url(#{id})" />
  <rect x={x0} y="0" width={Math.max(1, x1 - x0)} height={H} class="band" onpointerdown={(e) => down(e, "band")} />
  <line x1={x0} x2={x0} y1="0" y2={H} stroke={color} stroke-width="1.5" />
  <line x1={x1} x2={x1} y1="0" y2={H} stroke={color} stroke-width="1.5" />
  <rect x={x0 - 6} y="0" width="12" height={H} class="grip" onpointerdown={(e) => down(e, "lo")} />
  <rect x={x1 - 6} y="0" width="12" height={H} class="grip" onpointerdown={(e) => down(e, "hi")} />
</svg>

<style>
  .rh {
    width: 100%;
    display: block;
    background: var(--bg-deepest);
    border-radius: 4px;
    cursor: crosshair;
    touch-action: none;
  }
  .all {
    fill: rgba(255, 255, 255, 0.14);
  }
  .band {
    fill: rgba(255, 255, 255, 0.04);
    cursor: grab;
  }
  .grip {
    fill: transparent;
    cursor: ew-resize;
  }
</style>
