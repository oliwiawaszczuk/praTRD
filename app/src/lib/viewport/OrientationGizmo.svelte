<script lang="ts">
  // Blender-style navigation gizmo for the 3-D view, in anatomical axes (LPS world):
  //   click a bubble → look from that side (A = face, S = from above…) · drag the disc → orbit.
  // Colours follow Slicer's axes: L/R red, A/P green, S/I blue.
  import { onDestroy, untrack } from "svelte";
  import type { Vec3 } from "./geometry.ts";
  import type { VolumeRenderer3D } from "./VolumeRenderer3D.ts";

  let { renderer }: { renderer: VolumeRenderer3D | null } = $props();

  const SIZE = 96;
  const R = 34;
  const AXES: { label: string; v: Vec3; color: string; pos: boolean }[] = [
    { label: "L", v: [1, 0, 0], color: "#e05a5a", pos: true },
    { label: "R", v: [-1, 0, 0], color: "#e05a5a", pos: false },
    { label: "P", v: [0, 1, 0], color: "#6cbf6c", pos: true },
    { label: "A", v: [0, -1, 0], color: "#6cbf6c", pos: false },
    { label: "S", v: [0, 0, 1], color: "#5b9bd5", pos: true },
    { label: "I", v: [0, 0, -1], color: "#5b9bd5", pos: false },
  ];
  const TITLES: Record<string, string> = {
    L: "Widok z lewej", R: "Widok z prawej", A: "Widok z przodu", P: "Widok z tyłu",
    S: "Widok z góry", I: "Widok z dołu",
  };

  let tick = $state(0);
  let off: (() => void) | null = null;
  $effect(() => {
    off?.();
    let raf = 0;
    off = renderer?.onCamera(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => tick++);
    }) ?? null;
    untrack(() => tick++); // re-project for the new renderer without depending on tick
  });
  onDestroy(() => off?.());

  const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const bubbles = $derived.by(() => {
    void tick;
    if (!renderer) return [];
    const { right, up, back } = renderer.cameraBasis();
    return AXES.map((a) => ({
      ...a,
      x: SIZE / 2 + R * dot(a.v, right),
      y: SIZE / 2 - R * dot(a.v, up),
      depth: dot(a.v, back),
    })).sort((p, q) => p.depth - q.depth); // far first, near on top
  });

  function snap(v: Vec3): void {
    // looking along S/I: anterior up (face at the top); otherwise head up
    const up: Vec3 = Math.abs(v[2]) > 0.5 ? [0, -1, 0] : [0, 0, 1];
    renderer?.viewFrom(v, up);
  }

  let drag: { x: number; y: number; moved: boolean; axis: Vec3 | null } | null = null;
  function onDown(e: PointerEvent, axis: Vec3 | null): void {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, moved: false, axis };
  }
  function onMove(e: PointerEvent): void {
    if (!drag || !renderer) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    if (!drag.moved) renderer.beginInteraction();
    drag.moved = true;
    renderer.orbit(-dx * 0.8, dy * 0.8);
    drag.x = e.clientX;
    drag.y = e.clientY;
  }
  function onUp(): void {
    if (drag && !drag.moved && drag.axis) snap(drag.axis);
    if (drag?.moved) renderer?.endInteraction();
    drag = null;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  class="gizmo"
  width={SIZE}
  height={SIZE}
  viewBox="0 0 {SIZE} {SIZE}"
  onpointermove={onMove}
  onpointerup={onUp}
  onpointercancel={onUp}
  ondblclick={(e) => e.stopPropagation()}
>
  <circle class="disc" cx={SIZE / 2} cy={SIZE / 2} r={SIZE / 2 - 2} onpointerdown={(e) => onDown(e, null)} />
  {#each bubbles as b (b.label)}
    {#if b.pos}
      <line x1={SIZE / 2} y1={SIZE / 2} x2={b.x} y2={b.y} stroke={b.color} stroke-width="2" opacity="0.9" />
    {/if}
  {/each}
  {#each bubbles as b (b.label)}
    <g class="bubble" onpointerdown={(e) => onDown(e, b.v)}>
      <title>{TITLES[b.label]}</title>
      <circle
        cx={b.x}
        cy={b.y}
        r={b.pos ? 9 : 8}
        fill={b.pos ? b.color : "#1a1a1a"}
        stroke={b.color}
        stroke-width={b.pos ? 0 : 1.6}
        opacity={0.55 + 0.45 * ((b.depth + 1) / 2)}
      />
      <text x={b.x} y={b.y + 3.5} fill={b.pos ? "#111" : b.color}>{b.label}</text>
    </g>
  {/each}
</svg>

<style>
  .gizmo {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 5;
    overflow: visible;
    touch-action: none;
  }
  .disc {
    fill: rgba(255, 255, 255, 0);
    transition: fill 0.15s;
    cursor: grab;
  }
  .gizmo:hover .disc {
    fill: rgba(255, 255, 255, 0.07);
  }
  .bubble {
    cursor: pointer;
  }
  .bubble:hover circle {
    stroke: #fff;
    stroke-width: 2;
  }
  text {
    font-family: var(--font);
    font-size: 9.5px;
    font-weight: 700;
    text-anchor: middle;
    pointer-events: none;
  }
</style>
