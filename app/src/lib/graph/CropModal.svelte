<script lang="ts">
  // 3-D crop box editor (Unity-collider style) for the "Przytnij" node:
  // drag a face handle → that face moves along its axis; orbit/zoom with the mouse as in the
  // 3-D view. The volume is clipped live; Zastosuj writes the node params (one undo step).
  import { onDestroy } from "svelte";
  import { volumeMeta, volumePath, type VolumeEntry, type VolumeMeta } from "#lib/core/library.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import RangeSlider from "#lib/ui/RangeSlider.svelte";
  import { num } from "#lib/ui/format.ts";
  import type { LevelGeometry } from "#lib/core/library.svelte.ts";
  import { buildTf, defaultTf } from "#lib/viewport/presets.ts";
  import { scene } from "#lib/viewport/scene.svelte.ts";
  import { fetchLevel } from "#lib/viewport/volumeSource.ts";
  import { VolumeRenderer3D } from "#lib/viewport/VolumeRenderer3D.ts";
  import type { Vec3 } from "#lib/viewport/geometry.ts";
  import OrientationGizmo from "#lib/viewport/OrientationGizmo.svelte";
  import ProjectionToggle from "#lib/viewport/ProjectionToggle.svelte";
  import { AXES, boxFromParams, closeCrop, cropModal, type Box } from "./cropModal.svelte.ts";
  import { bestRun, type VolumeOut } from "./evaluation.svelte.ts";
  import { commit, graph, nodeById } from "./store.svelte.ts";

  const node = $derived(cropModal.nodeId ? nodeById(cropModal.nodeId) : undefined);
  const input = $derived.by(() => {
    if (!node) return null;
    const e = graph.doc.edges.find((x) => x.to === node.id && x.toSocket === "in");
    const r = e ? bestRun(e.from) : null;
    const o = r?.outputs?.[e!.fromSocket];
    return o && o.kind === "wolumen" ? (o as VolumeOut) : null;
  });

  let box = $state<Box>({ i: [0, 1], j: [0, 1], k: [0, 1] });
  $effect(() => {
    if (node) box = boxFromParams(node.params);
  });

  let host = $state<HTMLDivElement>();
  let r = $state.raw<VolumeRenderer3D | null>(null);
  let progress = $state<number | null>(0);
  let error = $state("");
  let geom = $state.raw<LevelGeometry | null>(null);

  // load the input volume (light level) into a dedicated renderer
  $effect(() => {
    const inp = input;
    if (!host || !inp) return;
    const ctl = new AbortController();
    const rr = new VolumeRenderer3D(host);
    if (import.meta.env.DEV) (window as unknown as { __pratrdCrop: unknown }).__pratrdCrop = rr;
    r = rr;
    progress = 0;
    error = "";
    (async () => {
      const m: VolumeMeta = await volumeMeta(inp.ref, ctl.signal);
      let L = m.levels.length - 1;
      for (let n = 0; n < m.levels.length; n++) {
        const s = m.levels[n].size;
        if (s[0] * s[1] * s[2] <= 24_000_000) {
          L = n;
          break;
        }
      }
      const d = await fetchLevel(volumePath(inp.ref), L, (p) => (progress = p), ctl.signal);
      if (ctl.signal.aborted) return;
      geom = m.levels[0];
      rr.setVolume(d.data, m.levels[L]);
      const entry = {
        modality: inp.info?.modality,
        stats: m.stats,
        window: inp.info?.window ?? { center: (m.stats.p1 + m.stats.p99) / 2, width: m.stats.p99 - m.stats.p1 },
      } as unknown as VolumeEntry; // buildTf only reads modality / stats / window
      const tf = scene.tf ?? defaultTf(entry);
      rr.setTransferFunction(buildTf(tf, entry, scene.wl ?? entry.window));
      rr.orbit(-35, 20); // three-quarter view: three faces visible at once
      rr.zoomBy(0.62); // whole box (and its handles) in frame
      progress = null;
    })().catch((e) => {
      if (!ctl.signal.aborted) {
        error = String(e?.message ?? e);
        progress = null;
      }
    });
    return () => {
      ctl.abort();
      rr.dispose();
      r = null;
    };
  });

  // ── box ↔ world ───────────────────────────────────────────────────────────
  const AX_COLORS = ["#e05a5a", "#6cbf6c", "#5b9bd5"]; // dominant LPS component x / y / z
  const axisDir = (g: LevelGeometry, a: number): Vec3 => [g.direction[a], g.direction[3 + a], g.direction[6 + a]];
  const dominant = (v: Vec3) => [0, 1, 2].reduce((b, c) => (Math.abs(v[c]) > Math.abs(v[b]) ? c : b), 0);

  function world(g: LevelGeometry, f: [number, number, number]): Vec3 {
    // fraction of the extent → world; voxel edges sit half a voxel before centres
    const t = f.map((x, a) => (x * g.size[a] - 0.5) * g.spacing[a]);
    const d = g.direction;
    return [
      g.origin[0] + d[0] * t[0] + d[1] * t[1] + d[2] * t[2],
      g.origin[1] + d[3] * t[0] + d[4] * t[1] + d[5] * t[2],
      g.origin[2] + d[6] * t[0] + d[7] * t[1] + d[8] * t[2],
    ];
  }

  // live clipping
  $effect(() => {
    const g = geom;
    if (!r || !g) return;
    const planes = AXES.flatMap((ax, a) => {
      const dir = axisDir(g, a);
      const lo: [number, number, number] = [0, 0, 0];
      const hi: [number, number, number] = [1, 1, 1];
      lo[a] = box[ax][0];
      hi[a] = box[ax][1];
      return [
        { origin: world(g, lo), normal: dir },
        { origin: world(g, hi), normal: [-dir[0], -dir[1], -dir[2]] as Vec3 },
      ];
    });
    r.setClipPlanes(planes);
  });

  // ── overlay (re-projected on every camera change) ────────────────────────────
  let tick = $state(0);
  $effect(() => {
    if (!r) return;
    let raf = 0;
    return r.onCamera(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => tick++);
    });
  });

  const corners = $derived.by(() => {
    void tick;
    const g = geom;
    if (!r || !g || progress !== null) return [];
    const out: { f: [number, number, number]; p: [number, number] }[] = [];
    for (const a of [0, 1]) for (const b of [0, 1]) for (const c of [0, 1]) {
      const f: [number, number, number] = [box.i[a], box.j[b], box.k[c]];
      out.push({ f, p: r.project(world(g, f)) });
    }
    return out;
  });
  const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];

  const handles = $derived.by(() => {
    void tick;
    const g = geom;
    if (!r || !g || progress !== null) return [];
    return AXES.flatMap((ax, a) =>
      ([0, 1] as const).map((side) => {
        const f: [number, number, number] = [(box.i[0] + box.i[1]) / 2, (box.j[0] + box.j[1]) / 2, (box.k[0] + box.k[1]) / 2];
        f[a] = box[ax][side];
        return { ax, a, side, p: r!.project(world(g, f)), color: AX_COLORS[dominant(axisDir(g, a))], f };
      }),
    );
  });

  let drag = $state<{
    ax: (typeof AXES)[number];
    a: number;
    side: 0 | 1;
    x: number;
    y: number;
    v: [number, number];
    L: number;
    start: [number, number];
  } | null>(null);
  let hoverAxis = $state<string | null>(null);
  let stageHovered = $state(false);

  function onHandleDown(e: PointerEvent, h: (typeof handles)[number]): void {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const g = geom!;
    // screen direction of this axis at the handle: project a 10 %-of-extent step
    const L = 0.1 * g.size[h.a] * g.spacing[h.a];
    const f2 = [...h.f] as [number, number, number];
    f2[h.a] += 0.1;
    const q = r!.project(world(g, f2));
    r?.beginInteraction();
    drag = { ax: h.ax, a: h.a, side: h.side, x: e.clientX, y: e.clientY, v: [q[0] - h.p[0], q[1] - h.p[1]], L, start: [...box[h.ax]] as [number, number] };
  }
  function onMove(e: PointerEvent): void {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    const vv = drag.v[0] ** 2 + drag.v[1] ** 2;
    if (vv < 1) return; // axis points at the camera — use the sliders
    const t = (dx * drag.v[0] + dy * drag.v[1]) / vv; // in units of 10 % of the extent
    const range: [number, number] = [...drag.start];
    const gap = 0.01;
    if (drag.side === 0) range[0] = Math.min(range[1] - gap, Math.max(0, drag.start[0] + t * 0.1));
    else range[1] = Math.max(range[0] + gap, Math.min(1, drag.start[1] + t * 0.1));
    box = { ...box, [drag.ax]: range };
  }

  function endDrag(): void {
    if (drag) r?.endInteraction();
    drag = null;
  }

  function apply(): void {
    if (!node) return;
    for (const ax of AXES) {
      node.params[`${ax}0`] = Math.round(box[ax][0] * 1000) / 10;
      node.params[`${ax}1`] = Math.round(box[ax][1] * 1000) / 10;
    }
    commit();
    closeCrop();
  }

  const axisInfo = $derived(
    geom
      ? AXES.map((ax, a) => {
          const dir = axisDir(geom!, a);
          const d = dominant(dir);
          const pos = dir[d] > 0;
          const ends = [["R", "L"], ["A", "P"], ["I", "S"]][d];
          const extent = geom!.size[a] * geom!.spacing[a];
          return { ax, color: AX_COLORS[d], lo: pos ? ends[0] : ends[1], hi: pos ? ends[1] : ends[0], extent };
        })
      : [],
  );

  function onKey(e: KeyboardEvent): void {
    if (!node) return;
    if (e.key === "Escape") closeCrop();
    else if (e.key === "Enter") apply();
  }
  onDestroy(() => r?.dispose());
</script>

<svelte:window onkeydown={onKey} />

{#if node}
  <div class="backdrop">
    <div class="modal" role="dialog" aria-label="Przycinanie 3D">
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="stage" onpointerenter={() => (stageHovered = true)} onpointerleave={() => (stageHovered = false)}>
        <div class="host" bind:this={host}></div>
        {#if !input}
          <div class="msg"><Icon name="alert" size={22} /> Podłącz wolumen do wejścia node'a</div>
        {/if}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <svg class="ov" onpointermove={onMove} onpointerup={endDrag} onpointercancel={endDrag}>
          {#each EDGES as [a, b], n (n)}
            {#if corners[a] && corners[b]}
              <line x1={corners[a].p[0]} y1={corners[a].p[1]} x2={corners[b].p[0]} y2={corners[b].p[1]} class="edge" />
            {/if}
          {/each}
          {#each handles as h (h.ax + h.side)}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <g
              class="h"
              class:hot={hoverAxis === h.ax || drag?.ax === h.ax}
              onpointerdown={(e) => onHandleDown(e, h)}
              onpointerenter={() => (hoverAxis = h.ax)}
              onpointerleave={() => (hoverAxis = null)}
            >
              <circle cx={h.p[0]} cy={h.p[1]} r="13" class="halo" />
              <circle cx={h.p[0]} cy={h.p[1]} r="7" fill={h.color} />
            </g>
          {/each}
        </svg>
        <OrientationGizmo renderer={r} />
        <ProjectionToggle renderer={r} hostHovered={stageHovered} />
        {#if progress !== null && input}
          <div class="load"><ProgressRing value={progress} size={54} /></div>
        {/if}
        {#if error}<div class="msg err">{error}</div>{/if}
      </div>

      <aside>
        <header>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" opacity=".35" /><path d="M8 9l4-2 4 2v5l-4 2-4-2z" />
          </svg>
          <span>Przytnij</span>
        </header>
        {#each axisInfo as a (a.ax)}
          <div class="axis" class:hot={hoverAxis === a.ax}>
            <div class="ends"><b style:color={a.color}>{a.lo}</b><span>{num((box[a.ax][1] - box[a.ax][0]) * a.extent, 0)} mm</span><b style:color={a.color}>{a.hi}</b></div>
            <RangeSlider
              lo={box[a.ax][0]}
              hi={box[a.ax][1]}
              color={a.color}
              onchange={(lo, hi) => (box = { ...box, [a.ax]: [lo, hi] })}
              onstart={() => r?.beginInteraction()}
              onend={() => r?.endInteraction()}
            />
          </div>
        {/each}
        <div class="grow"></div>
        <button class="btn" title="Cały wolumen" onclick={() => (box = { i: [0, 1], j: [0, 1], k: [0, 1] })}>
          <Icon name="undo" size={12} /> Reset
        </button>
        <div class="actions">
          <button class="btn" onclick={closeCrop}>Anuluj</button>
          <button class="btn primary" onclick={apply}><Icon name="check" size={12} /> Zastosuj</button>
        </div>
      </aside>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 900;
    background: var(--backdrop);
    display: flex;
    align-items: center;
    justify-content: center;
    animation: fade 0.15s ease;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .modal {
    width: min(1100px, calc(100vw - 60px));
    height: min(720px, calc(100vh - 60px));
    display: flex;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: 0 16px 50px rgba(0, 0, 0, 0.6);
  }
  .stage {
    position: relative;
    flex: 1;
    min-width: 0;
    background: #000;
  }
  .host {
    position: absolute;
    inset: 0;
  }
  .ov {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .edge {
    stroke: var(--accent);
    stroke-width: 1.4;
    opacity: 0.85;
  }
  .h {
    pointer-events: auto;
    cursor: grab;
  }
  .halo {
    fill: rgba(255, 255, 255, 0.08);
    stroke: rgba(255, 255, 255, 0.35);
    stroke-width: 1;
    transition: r 0.1s;
  }
  .h.hot .halo {
    fill: rgba(255, 255, 255, 0.2);
    stroke: #fff;
  }
  .load,
  .msg {
    position: absolute;
    inset: 0;
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: center;
    color: var(--text-dim-2);
    font-size: var(--fs-sm);
    pointer-events: none;
  }
  .err {
    color: var(--danger);
  }
  aside {
    width: 240px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px;
    border-left: 1px solid var(--line-1);
  }
  header {
    display: flex;
    align-items: center;
    gap: 9px;
    font-size: var(--fs-lg);
    font-weight: 600;
    color: var(--text-strong);
  }
  header svg {
    color: var(--accent);
  }
  .axis {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px;
    border-radius: var(--radius-sm);
    background: var(--bg-deep);
    border: 1px solid transparent;
  }
  .axis.hot {
    border-color: var(--line-3);
  }
  .ends {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
  }
  .ends b {
    font-weight: 700;
  }
  .grow {
    flex: 1;
  }
  .actions {
    display: flex;
    gap: 6px;
  }
  .actions .btn {
    flex: 1;
    justify-content: center;
  }
</style>
