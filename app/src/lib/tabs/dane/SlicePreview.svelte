<script lang="ts">
  import { untrack } from "svelte";
  import {
    volumeMeta,
    volumePath,
    type Axis,
    type VolumeEntry,
    type VolumeMeta,
  } from "#lib/core/library.svelte.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import { num } from "#lib/ui/format.ts";
  import { fetchSlice, windowToRgba, type Slice } from "#lib/viewport/slices.ts";

  let { vol }: { vol: VolumeEntry } = $props();

  const CT_PRESETS = [
    { name: "Mózg", center: 40, width: 80 },
    { name: "Tkanki miękkie", center: 40, width: 400 },
    { name: "Angio", center: 300, width: 600 },
    { name: "Kości", center: 400, width: 1800 },
    { name: "Płuca", center: -600, width: 1500 },
  ];

  let meta = $state<VolumeMeta | null>(null);
  let axis = $state<Axis>(wsGet<Axis>("dane_previewAxis", "k"));
  let index = $state(0); // level-0 units
  let center = $state(0);
  let width = $state(1);
  let canvas = $state<HTMLCanvasElement>();
  let box = $state<HTMLDivElement>();
  let boxW = $state(0);
  let boxH = $state(0);
  let slice = $state.raw<Slice | null>(null);
  let shownLevel = $state(0);
  let error = $state("");

  const axisLen = (a: Axis) => vol.size["ijk".indexOf(a)];

  // New volume: reset view, load level geometry.
  $effect(() => {
    const v = vol;
    untrack(() => {
      meta = null;
      slice = null;
      error = "";
      center = v.window.center;
      width = v.window.width;
      index = Math.floor(axisLen(axis) / 2);
    });
    const ctl = new AbortController();
    volumeMeta(v.id, ctl.signal)
      .then((m) => (meta = m))
      .catch((e) => !ctl.signal.aborted && (error = String(e?.message ?? e)));
    return () => ctl.abort();
  });

  // Slice plane in level-L terms: [rows axis, cols axis] (index into i,j,k).
  const plane: Record<Axis, [number, number]> = { k: [1, 0], j: [2, 0], i: [2, 1] };

  /** Smallest pyramid level that still covers the display at device resolution. */
  function pickLevel(m: VolumeMeta): number {
    const [r, c] = plane[axis];
    const dpr = window.devicePixelRatio || 1;
    let best = 0;
    for (let L = 0; L < m.levels.length; L++) {
      const s = m.levels[L].size;
      if (s[r] >= boxH * dpr * 0.9 && s[c] >= boxW * dpr * 0.9) best = L;
    }
    return best;
  }

  // Fetch: coalesced to one request per frame; a newer request aborts the older one.
  let ctl: AbortController | null = null;
  let raf = 0;
  $effect(() => {
    const m = meta;
    if (!m || !boxW || !boxH) return;
    const a = axis;
    const idx0 = index;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      const L = pickLevel(m);
      const n0 = m.levels[0].size["ijk".indexOf(a)];
      const nL = m.levels[L].size["ijk".indexOf(a)];
      const idxL = Math.min(nL - 1, Math.floor(((idx0 + 0.5) * nL) / n0));
      ctl?.abort();
      const c = (ctl = new AbortController());
      fetchSlice(volumePath(vol.id), a, idxL, L, c.signal)
        .then((s) => {
          if (c.signal.aborted) return;
          slice = s;
          shownLevel = L;
        })
        .catch((e) => {
          if (!c.signal.aborted) error = String(e?.message ?? e);
        });
    });
    return () => cancelAnimationFrame(raf);
  });

  // Draw: window → RGBA in an offscreen canvas, then scale with the physical aspect ratio.
  let off: HTMLCanvasElement | null = null;
  let img: ImageData | null = null;
  $effect(() => {
    const s = slice;
    const m = meta;
    if (!s || !m || !canvas || !boxW || !boxH) return;
    const c = center;
    const w = width;
    off ??= document.createElement("canvas");
    if (!img || img.width !== s.cols || img.height !== s.rows) {
      off.width = s.cols;
      off.height = s.rows;
      img = new ImageData(s.cols, s.rows);
    }
    windowToRgba(s, c, w, new Uint32Array(img.data.buffer), vol.stats);
    off.getContext("2d")!.putImageData(img, 0, 0);

    const g = m.levels[shownLevel];
    const [r, col] = plane[axis];
    const physH = s.rows * g.spacing[r];
    const physW = s.cols * g.spacing[col];
    const scale = Math.min(boxW / physW, boxH / physH);
    const dw = physW * scale;
    const dh = physH * scale;
    const dpr = window.devicePixelRatio || 1;
    // Resizing reallocates the backing store — only when the size really changed,
    // not on every W/L drag frame.
    const cw = Math.round(boxW * dpr);
    const ch = Math.round(boxH * dpr);
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.clearRect(0, 0, boxW, boxH);
    // Rows run along k for coronal/sagittal-type planes: if k points to the head (+S),
    // flip so that superior is up (full reorientation comes with the E2 viewports).
    const flip = axis !== "k" && g.direction[8] > 0;
    ctx.save();
    ctx.translate((boxW - dw) / 2, flip ? (boxH + dh) / 2 : (boxH - dh) / 2);
    if (flip) ctx.scale(1, -1);
    ctx.drawImage(off, 0, 0, dw, dh);
    ctx.restore();
  });

  $effect(() => {
    if (!box) return;
    const ro = new ResizeObserver(([e]) => {
      boxW = e.contentRect.width;
      boxH = e.contentRect.height;
    });
    ro.observe(box);
    return () => ro.disconnect();
  });

  function setAxis(a: Axis): void {
    axis = a;
    index = Math.floor(axisLen(a) / 2);
    wsSet("dane_previewAxis", a);
  }

  let wheelAcc = 0;
  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    wheelAcc += e.deltaY;
    const steps = Math.trunc(wheelAcc / 40);
    if (steps) {
      wheelAcc -= steps * 40;
      index = Math.min(axisLen(axis) - 1, Math.max(0, index + steps));
    }
  }

  // Left drag = window/level (horizontal → width, vertical → centre), as in most viewers.
  let drag: { x: number; y: number; c: number; w: number } | null = null;
  function onDown(e: PointerEvent): void {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, c: center, w: width };
  }
  function onMove(e: PointerEvent): void {
    if (!drag) return;
    const k = Math.max(1, (vol.stats.max - vol.stats.min) / 600);
    width = Math.max(1, drag.w + (e.clientX - drag.x) * k);
    center = drag.c - (e.clientY - drag.y) * k;
  }
  const onUp = () => (drag = null);

  function preset(v: string): void {
    if (v === "dicom") ({ center, width } = vol.window);
    else if (v === "auto") {
      center = (vol.stats.p1 + vol.stats.p99) / 2;
      width = Math.max(1, vol.stats.p99 - vol.stats.p1);
    } else {
      const p = CT_PRESETS[Number(v)];
      center = p.center;
      width = p.width;
    }
  }
</script>

<div class="preview">
  <div class="bar">
    {#each ["k", "j", "i"] as const as a (a)}
      <button class="seg" class:active={axis === a} onclick={() => setAxis(a)}>
        {vol.planes[a]}
      </button>
    {/each}
    <span class="spacer"></span>
    <select class="input sel" onchange={(e) => preset(e.currentTarget.value)} value="">
      <option value="" disabled>Okno…</option>
      <option value="dicom">Z serii</option>
      <option value="auto">Auto (1–99 %)</option>
      {#if vol.modality === "CT"}
        {#each CT_PRESETS as p, n (p.name)}
          <option value={String(n)}>{p.name} ({p.center}/{p.width})</option>
        {/each}
      {/if}
    </select>
  </div>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="stage"
    bind:this={box}
    onwheel={onWheel}
    onpointerdown={onDown}
    onpointermove={onMove}
    onpointerup={onUp}
    onpointercancel={onUp}
  >
    <canvas bind:this={canvas} style:width="{boxW}px" style:height="{boxH}px"></canvas>
    {#if error}<div class="overlay err">{error}</div>{/if}
    <div class="hud tl">{index + 1} / {axisLen(axis)}</div>
    <div class="hud tr">O: {num(center, 0)} · S: {num(width, 0)}</div>
    {#if meta}<div class="hud br">poziom {shownLevel}{shownLevel ? " (podgląd)" : ""}</div>{/if}
  </div>

  <input
    class="slider"
    type="range"
    min="0"
    max={axisLen(axis) - 1}
    bind:value={index}
    aria-label="Warstwa"
  />
</div>

<style>
  .preview {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .seg {
    padding: 4px 11px;
    font-size: var(--fs-xs);
    font-weight: 600;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-dim-3);
    cursor: pointer;
  }
  .seg:hover:not(.active) {
    background: var(--hover);
    color: var(--text-dim-1);
  }
  .seg.active {
    background: var(--accent-a10);
    border-color: var(--accent-a30);
    color: var(--accent);
  }
  .spacer {
    flex: 1;
  }
  .sel {
    width: auto;
    padding: 4px 8px;
    font-size: var(--fs-xs);
  }
  .stage {
    position: relative;
    flex: 1;
    min-height: 160px;
    background: #000;
    border-radius: var(--radius-sm);
    overflow: hidden;
    cursor: crosshair;
    touch-action: none;
  }
  canvas {
    position: absolute;
    inset: 0;
    display: block;
  }
  .hud {
    position: absolute;
    font-size: var(--fs-xs);
    color: rgba(255, 255, 255, 0.7);
    text-shadow: 0 1px 2px #000;
    pointer-events: none;
  }
  .tl {
    top: 8px;
    left: 10px;
  }
  .tr {
    top: 8px;
    right: 10px;
  }
  .br {
    bottom: 8px;
    right: 10px;
    color: var(--text-dim-3);
  }
  .overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-sm);
  }
  .err {
    color: var(--danger);
  }
  .slider {
    width: 100%;
    accent-color: var(--accent);
  }
</style>
