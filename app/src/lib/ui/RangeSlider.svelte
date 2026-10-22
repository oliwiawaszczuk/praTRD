<script lang="ts">
  // Two-thumb range slider (0..1). Drag a thumb, or the band between them to move both.
  let {
    lo,
    hi,
    color = "var(--accent)",
    onchange,
    onstart,
    onend,
  }: {
    lo: number;
    hi: number;
    color?: string;
    onchange: (lo: number, hi: number) => void;
    onstart?: () => void; // gesture begins (e.g. switch a renderer to interactive quality)
    onend?: () => void;
  } = $props();

  let el = $state<HTMLDivElement>();
  let drag: { what: "lo" | "hi" | "band"; x: number; lo: number; hi: number } | null = null;
  const MIN_GAP = 0.01;

  function frac(e: PointerEvent): number {
    const r = el!.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  }
  function down(e: PointerEvent, what: "lo" | "hi" | "band"): void {
    e.stopPropagation();
    el!.setPointerCapture(e.pointerId);
    if (!drag) onstart?.();
    drag = { what, x: frac(e), lo, hi };
  }
  function trackDown(e: PointerEvent): void {
    const f = frac(e);
    down(e, Math.abs(f - lo) < Math.abs(f - hi) ? "lo" : "hi");
    move(e);
  }
  function end(): void {
    if (drag) onend?.();
    drag = null;
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    const f = frac(e);
    if (drag.what === "lo") onchange(Math.min(f, hi - MIN_GAP), hi);
    else if (drag.what === "hi") onchange(lo, Math.max(f, lo + MIN_GAP));
    else {
      const d = Math.min(1 - drag.hi, Math.max(-drag.lo, f - drag.x));
      onchange(drag.lo + d, drag.hi + d);
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="rs"
  bind:this={el}
  style:--c={color}
  onpointerdown={trackDown}
  onpointermove={move}
  onpointerup={end}
  onpointercancel={end}
>
  <div class="rail"></div>
  <div class="band" style:left="{lo * 100}%" style:width="{(hi - lo) * 100}%" onpointerdown={(e) => down(e, "band")}></div>
  <div class="th" style:left="{lo * 100}%" onpointerdown={(e) => down(e, "lo")}></div>
  <div class="th" style:left="{hi * 100}%" onpointerdown={(e) => down(e, "hi")}></div>
</div>

<style>
  .rs {
    position: relative;
    height: 18px;
    cursor: pointer;
    touch-action: none;
  }
  .rail {
    position: absolute;
    left: 0;
    right: 0;
    top: 8px;
    height: 2px;
    background: var(--line-2);
    border-radius: 1px;
  }
  .band {
    position: absolute;
    top: 6px;
    height: 6px;
    background: var(--c);
    opacity: 0.45;
    border-radius: 3px;
    cursor: grab;
  }
  .th {
    position: absolute;
    top: 3px;
    width: 12px;
    height: 12px;
    margin-left: -6px;
    border-radius: 50%;
    background: var(--c);
    box-shadow: 0 0 0 2px var(--bg-panel);
    cursor: ew-resize;
  }
  .th:hover {
    transform: scale(1.2);
  }
</style>
