<script lang="ts">
  // 3-D volume rendering. Progressive: a coarse level (≤ ~2 M voxels, a few MB) appears
  // almost instantly, then the largest level within the GPU budget replaces it.
  import { volumePath, type VolumeEntry, type VolumeMeta } from "#lib/core/library.svelte.ts";
  import { dims } from "#lib/ui/format.ts";
  import { buildTf } from "./presets.ts";
  import { level3d, scene, toggleMaximized } from "./scene.svelte.ts";
  import { fetchLevel } from "./volumeSource.ts";
  import { VolumeRenderer3D } from "./VolumeRenderer3D.ts";
  import OrientationGizmo from "./OrientationGizmo.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { untrack } from "svelte";
  import ProjectionToggle from "./ProjectionToggle.svelte";
  import SlicePlanes3D from "./SlicePlanes3D.svelte";
  import MarkupLayer3D from "./MarkupLayer3D.svelte";
  import { draftClick, draftHover } from "./markupDraft.svelte.ts";
  import type { MarkupType } from "./markups.ts";
  import { NO_LAYERS, type SliceLayers, type Stroke } from "./layers.ts";
  import type { Vec3 } from "./geometry.ts";

  let { vol, meta, layers = NO_LAYERS }: { vol: VolumeEntry; meta: VolumeMeta; layers?: SliceLayers } = $props();
  const overlay = $derived(layers.overlay);

  let host = $state<HTMLDivElement>();
  let r = $state.raw<VolumeRenderer3D | null>(null);
  let progress = $state<number | null>(null);
  // captured at load time — never index the CURRENT meta with a level of a previous volume
  let shownLevel = $state<{ level: number; size: [number, number, number] } | null>(null);
  let error = $state("");
  let attempt = $state(0); // bump to retry a failed load

  let hovered = $state(false);

  $effect(() => {
    if (!host) return;
    // local variable: this effect must never READ `r` (it writes it — that would loop)
    let created: VolumeRenderer3D | null = null;
    try {
      created = new VolumeRenderer3D(host);
      if (import.meta.env.DEV) (window as unknown as { __pratrd3d: unknown }).__pratrd3d = created;
    } catch (e) {
      error = String((e as Error).message);
    }
    r = created;
    return () => {
      created?.dispose();
      r = null;
    };
  });

  // Load the volume progressively whenever the volume changes.
  $effect(() => {
    const v = vol;
    const m = meta;
    void attempt;
    if (!r) return;
    const ctl = new AbortController();
    const target = level3d(m);
    let preview = target;
    for (let L = target; L < m.levels.length; L++) {
      const s = m.levels[L].size;
      preview = L;
      if (s[0] * s[1] * s[2] <= 2_000_000) break;
    }
    const steps = preview > target ? [preview, target] : [target];
    shownLevel = null;
    error = "";
    (async () => {
      let first = true;
      for (const L of steps) {
        progress = 0;
        const d = await fetchLevel(volumePath(v.id), L, (p) => (progress = p), ctl.signal);
        if (ctl.signal.aborted || !r) return;
        r.setVolume(d.data, m.levels[L]);
        if (first) applyTf();
        first = false;
        shownLevel = { level: L, size: m.levels[L].size };
      }
      progress = null;
    })().catch((e) => {
      if (!ctl.signal.aborted) {
        error = String(e?.message ?? e);
        progress = null;
      }
    });
    return () => ctl.abort();
  });

  // Segment overlay: largest level within ~64 M voxels (uint8 → ≤ 64 MB on the GPU).
  let ovLoading = $state(false);
  $effect(() => {
    const o = overlay;
    const rr = r;
    if (!rr) return;
    if (!o) {
      rr.setOverlay(null, null, {});
      return;
    }
    const ctl = new AbortController();
    let L = o.meta.levels.length - 1;
    for (let n = 0; n < o.meta.levels.length; n++) {
      const sz = o.meta.levels[n].size;
      if (sz[0] * sz[1] * sz[2] <= 64_000_000) {
        L = n;
        break;
      }
    }
    ovLoading = true;
    fetchLevel(volumePath(o.ref), L, () => {}, ctl.signal)
      .then((d) => {
        if (ctl.signal.aborted) return;
        rr.setOverlay(d.data, o.meta.levels[L], o.colors);
        // strokes committed after this result was computed: keep them visible
        for (const st of untrack(() => layers.pending)) paintStroke(rr, st);
      })
      .catch(() => {})
      .finally(() => {
        if (!ctl.signal.aborted) ovLoading = false;
      });
    return () => ctl.abort();
  });

  // ── brush / eraser on the 3-D surface ──
  const brushing = $derived(layers.tool === "brush" || layers.tool === "erase");
  let painting: Stroke | null = null;
  let cursor = $state<{ x: number; y: number; r: number } | null>(null);

  function paintStroke(rr: VolumeRenderer3D, st: Stroke): void {
    for (const p of st.p) rr.paint(p, st.r, st.mode === "add", layers.color);
  }
  function local(e: PointerEvent): [number, number] {
    const b = host!.getBoundingClientRect();
    return [e.clientX - b.left, e.clientY - b.top];
  }
  /** Erase digs into the mask; add sits on visible tissue (not on its own fresh paint). */
  function hitAt(x: number, y: number, mode: Stroke["mode"]): Vec3 | null {
    if (!r) return null;
    if (mode === "erase") return r.pick(x, y, { mask: true, tissue: false });
    return r.pick(x, y, { mask: !painting, tissue: true }) ?? r.pick(x, y, { mask: true, tissue: false });
  }
  function showCursor(x: number, y: number, hit: Vec3 | null): void {
    if (!hit || !r) {
      cursor = null;
      return;
    }
    const { right } = r.cameraBasis();
    const R = layers.brushR;
    const [cx, cy] = r.project(hit);
    const [ex, ey] = r.project([hit[0] + right[0] * R, hit[1] + right[1] * R, hit[2] + right[2] * R]);
    cursor = { x: cx, y: cy, r: Math.max(2, Math.hypot(ex - cx, ey - cy)) };
  }
  // markups in 3-D: point / ruler / angle placed by clicking on a surface (ROI: 2-D views)
  const placing = $derived(
    layers.toolNode && (layers.tool === "point" || layers.tool === "line" || layers.tool === "angle")
      ? (layers.tool as MarkupType)
      : null,
  );
  const surfaceAt = (x: number, y: number) => r?.pick(x, y, { mask: true, tissue: true }) ?? null;
  function placeDown(e: PointerEvent): boolean {
    if (!placing || !layers.toolNode || e.button !== 0 || e.shiftKey) return false;
    const hit = surfaceAt(...local(e));
    if (!hit) return false; // empty space: orbit as usual
    e.stopPropagation();
    e.preventDefault();
    const node = layers.toolNode;
    const items = layers.markups.find((g) => g.nodeId === node)?.items ?? [];
    const done = draftClick(node, placing, hit, items);
    if (done) layers.onMarkups?.(node, done);
    return true;
  }

  // capture phase: a stroke that starts on a structure never reaches vtk.js (no orbit);
  // in empty space, with Shift or another button the view orbits as usual
  function onDownCapture(e: PointerEvent): void {
    if (placeDown(e)) return;
    if (!brushing || !r || e.button !== 0 || e.shiftKey) return;
    const [x, y] = local(e);
    const mode: Stroke["mode"] = layers.tool === "erase" ? "erase" : "add";
    const hit = hitAt(x, y, mode);
    if (!hit) return;
    e.stopPropagation();
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    painting = { p: [hit], r: layers.brushR, mode };
    r.beginInteraction();
    r.paint(hit, painting.r, mode === "add", layers.color);
    showCursor(x, y, hit);
  }
  let moveRaf = 0;
  let lastMove: PointerEvent | null = null;
  function onMoveCapture(e: PointerEvent): void {
    if (placing && !e.buttons) {
      const hit = surfaceAt(...local(e));
      if (hit) draftHover(hit);
    }
    if (!brushing) {
      cursor = null;
      return;
    }
    if (painting) e.stopPropagation();
    lastMove = e;
    if (moveRaf) return;
    // one pick per frame, however fast the pointer events come
    moveRaf = requestAnimationFrame(() => {
      moveRaf = 0;
      const ev = lastMove;
      if (!ev || !r) return;
      const [x, y] = local(ev);
      const mode: Stroke["mode"] = painting?.mode ?? (layers.tool === "erase" ? "erase" : "add");
      const hit = hitAt(x, y, mode);
      showCursor(x, y, hit);
      if (painting && hit) {
        const last = painting.p[painting.p.length - 1];
        if (Math.hypot(hit[0] - last[0], hit[1] - last[1], hit[2] - last[2]) >= painting.r / 3) {
          painting.p.push(hit);
          r.paint(hit, painting.r, mode === "add", layers.color);
        }
      }
    });
  }
  function onUpCapture(e: PointerEvent): void {
    if (!painting) return;
    e.stopPropagation();
    const st = painting;
    painting = null;
    r?.endInteraction();
    layers.onStroke?.(st);
  }
  $effect(() => {
    if (!brushing) cursor = null;
  });

  function applyTf(): void {
    if (r && scene.tf && scene.wl) r.setTransferFunction(buildTf(scene.tf, vol, scene.wl));
  }

  // Transfer function follows the preset (and W/L for MIP).
  $effect(() => {
    void [scene.tf, scene.tf === "mip" ? scene.wl : null];
    applyTf();
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="view3d"
  ondblclick={() => !layers.tool && toggleMaximized("3d")}
  onpointerenter={() => (hovered = true)}
  onpointerleave={() => {
    hovered = false;
    cursor = null;
  }}
  onpointerdowncapture={onDownCapture}
  onpointermovecapture={onMoveCapture}
  onpointerupcapture={onUpCapture}
  onpointercancelcapture={onUpCapture}
  class:brushing={brushing || !!placing}
>
  <div class="host" bind:this={host}></div>
  <div class="hud tl"><b>3D</b></div>
  {#if shownLevel}
    <div class="hud br">poziom {shownLevel.level} · {dims(shownLevel.size)}</div>
  {/if}
  {#if shownLevel}<SlicePlanes3D renderer={r} geometry={meta.levels[0]} />{/if}
  {#if cursor}
    <svg class="brush" aria-hidden="true">
      <circle
        cx={cursor.x}
        cy={cursor.y}
        r={cursor.r}
        fill="none"
        stroke={layers.tool === "erase" ? "#fff" : layers.color}
        stroke-width="1.5"
        stroke-dasharray={layers.tool === "erase" ? "4 3" : null}
      />
    </svg>
  {/if}
  <MarkupLayer3D renderer={r} {layers} />
  <OrientationGizmo renderer={r} />
  <ProjectionToggle renderer={r} hostHovered={hovered} />
  {#if ovLoading && progress === null}
    <div class="load corner"><ProgressRing size={24} /></div>
  {/if}
  {#if progress !== null}
    <!-- nothing on screen yet: big centred ring; refining a preview: small corner ring -->
    <div class="load" class:corner={shownLevel !== null}>
      <ProgressRing value={progress} size={shownLevel !== null ? 30 : 54} />
    </div>
  {/if}
  {#if error}
    <div class="err">
      {error}
      <button class="btn" onclick={() => attempt++}>Spróbuj ponownie</button>
    </div>
  {/if}
</div>

<style>
  .view3d {
    position: relative;
    width: 100%;
    height: 100%;
    background: #000;
    overflow: hidden;
    border-top: 2px solid var(--port-wolumen);
  }
  .host {
    position: absolute;
    inset: 0;
  }
  .brushing .host {
    cursor: crosshair;
  }
  .brush {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .hud {
    position: absolute;
    font-size: var(--fs-xs);
    color: rgba(255, 255, 255, 0.75);
    text-shadow: 0 1px 2px #000;
    pointer-events: none;
  }
  .hud b {
    color: var(--port-wolumen);
  }
  .tl {
    top: 6px;
    left: 8px;
  }
  .br {
    bottom: 6px;
    right: 8px;
    color: var(--text-dim-3);
  }
  .load {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.45);
    pointer-events: none;
    animation: fade 0.2s ease;
  }
  .load.corner {
    inset: auto auto 8px 8px;
    background: none;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .err {
    position: absolute;
    inset: auto 8px 8px 8px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: var(--fs-xs);
    color: var(--danger);
  }
</style>
