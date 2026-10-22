<script lang="ts">
  // One anatomical 2-D view (axial / coronal / sagittal) of the scene volume.
  //  wheel            → slice (moves the shared cursor along this view's normal)
  //  click / drag     → cursor (all views follow)
  //  right drag       → window/level         ctrl|⌘ + wheel / pinch → zoom at mouse
  //  middle or ⇧ drag → pan                  double click            → maximize
  import { onDestroy } from "svelte";
  import { volumePath, type VolumeEntry, type VolumeMeta } from "#lib/core/library.svelte.ts";
  import { num } from "#lib/ui/format.ts";
  import {
    AXIS_NAME,
    edgeLetters,
    ijkToWorld,
    PLANE_COLOR,
    PLANE_LABEL,
    SLICE_ROWS_COLS,
    viewBasis,
    worldToIjk,
    type Plane,
    type Vec3,
  } from "./geometry.ts";
  import { scene, setCursor, setWL, toggleMaximized } from "./scene.svelte.ts";
  import { SliceLoader, type Slice, type SliceRequest } from "./slices.ts";
  import { SliceRenderer } from "./SliceRenderer.ts";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { hexRgb, NO_LAYERS, type SliceLayers, type Stroke } from "./layers.ts";
  import { rasterizeStrokes } from "./strokes.ts";
  import MarkupLayer2D from "./MarkupLayer2D.svelte";
  import type { ViewProj } from "./layers.ts";

  let {
    plane,
    vol,
    meta,
    frameKey,
    layers = NO_LAYERS,
  }: { plane: Plane; vol: VolumeEntry; meta: VolumeMeta; frameKey: string; layers?: SliceLayers } = $props();

  let host = $state<HTMLDivElement>();
  let glCanvas = $state<HTMLCanvasElement>();
  let overlay = $state<HTMLCanvasElement>();
  let W = $state(0);
  let H = $state(0);
  let dpr = $state(window.devicePixelRatio || 1);
  let renderer: SliceRenderer | null = null;
  let glError = $state("");

  const g0 = $derived(meta.levels[0]);
  const basis = $derived(viewBasis(g0, plane));
  const su = $derived(g0.spacing[basis.uAxis]);
  const sv = $derived(g0.spacing[basis.vAxis]);
  const signU = $derived(basis.uFlip ? -1 : 1);
  const signV = $derived(basis.vFlip ? -1 : 1);

  // Framing lives in WORLD units (centre in LPS mm, scale in px/mm), not voxel indices:
  // when a graph node's result changes geometry (crop shifts the origin, resample changes
  // the voxel size) the image stays exactly where it was on screen. null = fit to volume.
  let centerW = $state<Vec3 | null>(null);
  let scale = $state<number | null>(null);
  $effect(() => {
    // reset only when WHAT is displayed changes, not when a node's result updates
    void frameKey;
    centerW = null;
    scale = null;
  });

  const fit = $derived(
    W && H ? Math.min(W / (g0.size[basis.uAxis] * su), H / (g0.size[basis.vAxis] * sv)) : 1,
  );
  const pxPerMm = $derived(scale ?? fit); // CSS px per mm
  const centerIjk = $derived(
    centerW
      ? worldToIjk(g0, centerW)
      : ([(g0.size[0] - 1) / 2, (g0.size[1] - 1) / 2, (g0.size[2] - 1) / 2] as Vec3),
  );
  const cu = $derived(centerIjk[basis.uAxis]);
  const cv = $derived(centerIjk[basis.vAxis]);
  function setCenter(u: number, v: number): void {
    const ijk: Vec3 = [...centerIjk] as Vec3;
    ijk[basis.uAxis] = u;
    ijk[basis.vAxis] = v;
    centerW = ijkToWorld(g0, ijk);
  }

  const cursorIjk = $derived(scene.cursor ? worldToIjk(g0, scene.cursor) : null);
  const nSlices = $derived(g0.size[basis.sliceAxis]);
  const sliceIdx = $derived(
    cursorIjk ? Math.min(nSlices - 1, Math.max(0, Math.round(cursorIjk[basis.sliceAxis]))) : 0,
  );

  /** Coarsest level whose texels are still ≤ 1.5 device px — full detail, minimal bytes. */
  function pickLevel(): number {
    let best = 0;
    for (let L = 0; L < meta.levels.length; L++) {
      const s = meta.levels[L].spacing;
      if (Math.max(s[basis.uAxis], s[basis.vAxis]) * pxPerMm * dpr <= 1.5) best = L;
    }
    return best;
  }

  // ── loading ────────────────────────────────────────────────────────────────
  let delivered = $state.raw<{ slice: Slice; req: SliceRequest } | null>(null);
  let wanted = $state("");
  // loading = what we asked for is not what is on screen (shown after 150 ms, no flashing)
  const pending = $derived(
    !!wanted &&
      (!delivered ||
        wanted !== `${delivered.req.path}|${delivered.req.level}|${delivered.req.axis}|${delivered.req.index}`),
  );
  let showLoading = $state(false);
  $effect(() => {
    if (!pending) {
      showLoading = false;
      return;
    }
    const t = setTimeout(() => (showLoading = true), 150);
    return () => clearTimeout(t);
  });
  // Only a slice of the CURRENT volume may be drawn or probed: right after a switch (e.g. a
  // graph result with a different pyramid) the last delivered slice belongs to the old one.
  const shown = $derived(
    delivered && delivered.req.path === volumePath(vol.id) && meta.levels[delivered.req.level] ? delivered : null,
  );
  let loadError = $state("");
  let lastDir = 1;
  let prevIdx = -1;
  const loader = new SliceLoader(
    (slice, req) => {
      renderer?.upload(slice);
      delivered = { slice, req };
      loadError = "";
      if (import.meta.env.DEV) {
        // measurement hook for headless perf tests (dev builds only)
        const w = window as unknown as { __pratrdShown?: Record<string, unknown> };
        (w.__pratrdShown ??= {})[plane] = { index: req.index, level: req.level, t: performance.now() };
      }
    },
    (e) => (loadError = String((e as Error)?.message ?? e)),
  );
  onDestroy(() => loader.dispose());

  $effect(() => {
    if (!W || !H || !scene.cursor) return;
    const L = pickLevel();
    const n0 = nSlices;
    const nL = meta.levels[L].size[basis.sliceAxis];
    const idxL = Math.min(nL - 1, Math.floor(((sliceIdx + 0.5) * nL) / n0));
    if (prevIdx >= 0 && sliceIdx !== prevIdx) lastDir = sliceIdx > prevIdx ? 1 : -1;
    prevIdx = sliceIdx;
    const path = volumePath(vol.id);
    const axis = AXIS_NAME[basis.sliceAxis];
    const req = { path, axis, index: idxL, level: L };
    const prefetch: SliceRequest[] = [];
    for (let d = 1; d <= 4; d++) {
      const i = idxL + d * lastDir;
      if (i >= 0 && i < nL) prefetch.push({ path, axis, index: i, level: L });
    }
    wanted = `${req.path}|${req.level}|${req.axis}|${req.index}`;
    loader.request(req, prefetch);
  });

  // ── overlay (label volume, own geometry and pyramid) ────────────────────────
  let ovDelivered = $state.raw<{ slice: Slice; req: SliceRequest } | null>(null);
  let ovVisible = $state(false); // false when the current plane lies outside the overlay
  const ovLoader = new SliceLoader((slice, req) => {
    renderer?.uploadLabels(slice);
    ovDelivered = { slice, req };
  });
  onDestroy(() => ovLoader.dispose());
  const ov = $derived(layers.overlay);
  const ovBasis = $derived(ov ? viewBasis(ov.meta.levels[0], plane) : null);

  // LUT is (re)uploaded in draw() when it changes — never from an effect that could run
  // before the renderer exists (that left the colour table empty → black overlay).
  let appliedLut = "";

  $effect(() => {
    const o = ov;
    const ob = ovBasis;
    if (!o || !ob || !W || !H || !scene.cursor) {
      ovVisible = false;
      return;
    }
    let L = 0;
    for (let n = 0; n < o.meta.levels.length; n++) {
      const sp = o.meta.levels[n].spacing;
      if (Math.max(sp[ob.uAxis], sp[ob.vAxis]) * pxPerMm * dpr <= 1.5) L = n;
    }
    const gL = o.meta.levels[L];
    // the overlay slice through the plane currently shown (cursor moved onto this slice)
    const ijk: Vec3 = [...(cursorIjk as Vec3)];
    ijk[basis.sliceAxis] = sliceIdx;
    const idx = Math.round(worldToIjk(gL, ijkToWorld(g0, ijk))[ob.sliceAxis]);
    if (idx < 0 || idx >= gL.size[ob.sliceAxis]) {
      ovVisible = false;
      return;
    }
    ovVisible = true;
    ovLoader.request({ path: volumePath(o.ref), axis: AXIS_NAME[ob.sliceAxis], index: idx, level: L });
  });
  const ovShown = $derived(
    ov && ovVisible && ovDelivered && ovDelivered.req.path === volumePath(ov.ref) && ov.meta.levels[ovDelivered.req.level]
      ? ovDelivered
      : null,
  );

  /** World axis (0 x, 1 y, 2 z) an index axis mostly runs along. */
  const worldAxis = (c: 0 | 1 | 2): number => {
    const d = g0.direction;
    const v = [Math.abs(d[c]), Math.abs(d[3 + c]), Math.abs(d[6 + c])];
    return v.indexOf(Math.max(...v));
  };
  // handed to overlay layers (markups); rebuilt when the framing or the slice changes
  const proj = $derived.by<ViewProj>(() => {
    void [W, H, cu, cv, pxPerMm, sliceIdx, basis];
    const ss = g0.spacing[basis.sliceAxis];
    return {
      W,
      H,
      toScreen: (w) => {
        const ijk = worldToIjk(g0, w);
        return toScreen(ijk[basis.uAxis], ijk[basis.vAxis]);
      },
      depth: (w) => (worldToIjk(g0, w)[basis.sliceAxis] - sliceIdx) * ss,
      worldAt,
      tol: ss / 2 + 0.01,
      axes: [worldAxis(basis.uAxis), worldAxis(basis.vAxis), worldAxis(basis.sliceAxis)],
    };
  });

  /** World point (LPS) on the CURRENT slice plane under a CSS-pixel position. */
  function worldAt(x: number, y: number): Vec3 {
    const [iu, iv] = fromScreen(x, y);
    const ijk: Vec3 = [0, 0, 0];
    ijk[basis.uAxis] = iu;
    ijk[basis.vAxis] = iv;
    ijk[basis.sliceAxis] = sliceIdx;
    return ijkToWorld(g0, ijk);
  }

  /** Device px → texel coords of ANY volume level crossing this plane (affine: built from
   * three points through the world). Used for the overlay, whose grid differs from ours. */
  function screenToTexOf(gL: VolumeMeta["levels"][number], b: { sliceAxis: 0 | 1 | 2 }): number[] {
    const [rows, cols] = SLICE_ROWS_COLS[b.sliceAxis];
    const at = (xd: number, yd: number) => {
      const ijk = worldToIjk(gL, worldAt(xd / dpr, yd / dpr));
      return [ijk[cols] + 0.5, ijk[rows] + 0.5];
    };
    const p0 = at(0, 0);
    const px = at(1, 0);
    const py = at(0, 1);
    return [px[0] - p0[0], py[0] - p0[0], p0[0], px[1] - p0[1], py[1] - p0[1], p0[1], 0, 0, 1];
  }

  // ── screen ↔ volume mapping ────────────────────────────────────────────────
  /** Row-major 3×3: device px (y down) → texel coords of the SHOWN slice (its own level). */
  function screenToTex(level: number): number[] {
    const gL = meta.levels[level];
    const sLu = gL.spacing[basis.uAxis];
    const sLv = gL.spacing[basis.vAxis];
    const ru = su / sLu;
    const rv = sv / sLv;
    // tex_u = (cu + 0.5)·ru + signU·(x/dpr − W/2)/(pxPerMm·sLu)
    const au = signU / (dpr * pxPerMm * sLu);
    const bu = (cu + 0.5) * ru - (signU * (W / 2)) / (pxPerMm * sLu);
    const av = signV / (dpr * pxPerMm * sLv);
    const bv = (cv + 0.5) * rv - (signV * (H / 2)) / (pxPerMm * sLv);
    const [rowsAxis] = SLICE_ROWS_COLS[basis.sliceAxis];
    // texture x runs along the slice's column axis, y along its row axis
    return rowsAxis === basis.vAxis
      ? [au, 0, bu, 0, av, bv, 0, 0, 1]
      : [0, av, bv, au, 0, bu, 0, 0, 1];
  }

  const toScreen = (iu: number, iv: number): [number, number] => [
    W / 2 + signU * (iu - cu) * pxPerMm * su,
    H / 2 + signV * (iv - cv) * pxPerMm * sv,
  ];
  const fromScreen = (x: number, y: number): [number, number] => [
    cu + (signU * (x - W / 2)) / (pxPerMm * su),
    cv + (signV * (y - H / 2)) / (pxPerMm * sv),
  ];

  // ── drawing (on demand, one rAF per change) ──────────────────────────────────
  let raf = 0;
  $effect(() => {
    // dependencies
    const s = shown;
    const wl = scene.wl;
    const ci = cursorIjk;
    void [W, H, dpr, cu, cv, pxPerMm, ci, s, wl, ovShown, layers, strokeTick, hover];
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(draw);
  });

  function draw(): void {
    if (!glCanvas || !overlay || !W || !H) return;
    const cw = Math.round(W * dpr);
    const ch = Math.round(H * dpr);
    for (const c of [glCanvas, overlay]) {
      if (c.width !== cw || c.height !== ch) {
        c.width = cw;
        c.height = ch;
      }
    }
    const lutKey = JSON.stringify(ov?.colors ?? {});
    if (renderer && lutKey !== appliedLut) {
      renderer.setLut(ov?.colors ?? {});
      appliedLut = lutKey;
    }
    if (renderer && shown && scene.wl) {
      const texelPx = Math.max(
        meta.levels[shown.req.level].spacing[basis.uAxis],
        meta.levels[shown.req.level].spacing[basis.vAxis],
      ) * pxPerMm * dpr;
      // pending strokes → edit mask on the overlay's own grid (same voxels as the result)
      editApplied = false;
      const strokes = liveStrokes();
      if (ovShown && ov && ovBasis && strokes.length) {
        const n = ovShown.slice.rows * ovShown.slice.cols;
        if (editBuf.length !== n) editBuf = new Uint8Array(n);
        const any = rasterizeStrokes(editBuf, ov.meta.levels[ovShown.req.level], ovBasis.sliceAxis, ovShown.req.index, strokes);
        renderer.uploadEdit(any ? editBuf : null);
        editApplied = true;
      } else renderer.uploadEdit(null);
      renderer.draw({
        screenToTex: screenToTex(shown.req.level),
        center: scene.wl.center,
        width: scene.wl.width,
        smooth: texelPx < 6, // keep voxels crisp when zoomed far in
        overlay:
          ovShown && ov && ovBasis && !layers.threshold
            ? { screenToTex: screenToTexOf(ov.meta.levels[ovShown.req.level], ovBasis), alpha: layers.alpha, outline: layers.outline }
            : null,
        threshold: layers.threshold
          ? { lo: layers.threshold.lo, hi: layers.threshold.hi, color: hexRgb(layers.threshold.color) }
          : null,
      });
    } else renderer?.clear();
    drawOverlay();
  }

  const OTHER: Record<Plane, { vertical: Plane; horizontal: Plane }> = {
    axial: { vertical: "sagittal", horizontal: "coronal" },
    coronal: { vertical: "sagittal", horizontal: "axial" },
    sagittal: { vertical: "coronal", horizontal: "axial" },
  };

  /** Screen position + in-plane radius of a world sphere (r mm), or null if it misses the slice. */
  function sphereOnSlice(w: Vec3, r: number): [number, number, number] | null {
    const ijk = worldToIjk(g0, w);
    const d = Math.abs(ijk[basis.sliceAxis] - sliceIdx) * g0.spacing[basis.sliceAxis];
    if (d >= r) return null;
    const [x, y] = toScreen(ijk[basis.uAxis], ijk[basis.vAxis]);
    return [x, y, Math.sqrt(r * r - d * d) * pxPerMm];
  }

  function drawTools(ctx: CanvasRenderingContext2D): void {
    // no overlay to edit yet (empty start): added strokes as plain disks
    for (const st of editApplied ? [] : liveStrokes()) {
      if (st.mode === "erase") continue;
      ctx.fillStyle = layers.color;
      ctx.globalAlpha = 0.55;
      for (const p of st.p) {
        const c = sphereOnSlice(p, st.r);
        if (!c) continue;
        ctx.beginPath();
        ctx.arc(c[0], c[1], c[2], 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    // seeds near this slice
    for (const sd of layers.seeds) {
      const c = sphereOnSlice(sd, 3 * g0.spacing[basis.sliceAxis] + 0.5);
      if (!c) continue;
      ctx.beginPath();
      ctx.arc(c[0], c[1], 5, 0, Math.PI * 2);
      ctx.fillStyle = layers.color;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    }
    // brush cursor
    if (hover && (layers.tool === "brush" || layers.tool === "erase")) {
      ctx.beginPath();
      ctx.arc(hover.x, hover.y, layers.brushR * pxPerMm, 0, Math.PI * 2);
      ctx.lineWidth = 1.5;
      ctx.setLineDash(layers.tool === "erase" ? [4, 3] : []);
      ctx.strokeStyle = layers.tool === "erase" ? "#fff" : layers.color;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function drawOverlay(): void {
    const ctx = overlay!.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    drawTools(ctx);
    if (!cursorIjk || layers.tool) return; // no crosshair while a tool is in use
    const [x, y] = toScreen(cursorIjk[basis.uAxis], cursorIjk[basis.vAxis]);
    const gap = 10;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.75;
    ctx.strokeStyle = PLANE_COLOR[OTHER[plane].vertical];
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, y - gap);
    ctx.moveTo(x + 0.5, y + gap);
    ctx.lineTo(x + 0.5, H);
    ctx.stroke();
    ctx.strokeStyle = PLANE_COLOR[OTHER[plane].horizontal];
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(x - gap, y + 0.5);
    ctx.moveTo(x + gap, y + 0.5);
    ctx.lineTo(W, y + 0.5);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // ── setup ───────────────────────────────────────────────────────────────────
  $effect(() => {
    if (!glCanvas) return;
    try {
      renderer = new SliceRenderer(glCanvas);
    } catch (e) {
      glError = String((e as Error).message);
    }
    return () => {
      renderer?.dispose();
      renderer = null;
      appliedLut = "";
    };
  });

  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver(([e]) => {
      W = e.contentRect.width;
      H = e.contentRect.height;
      dpr = window.devicePixelRatio || 1;
    });
    ro.observe(host);
    return () => ro.disconnect();
  });

  // ── interaction ─────────────────────────────────────────────────────────────
  function cursorAt(x: number, y: number): void {
    if (!cursorIjk) return;
    const [iu, iv] = fromScreen(x, y);
    const ijk: Vec3 = [...cursorIjk] as Vec3;
    ijk[basis.uAxis] = Math.min(g0.size[basis.uAxis] - 1, Math.max(0, iu));
    ijk[basis.vAxis] = Math.min(g0.size[basis.vAxis] - 1, Math.max(0, iv));
    ijk[basis.sliceAxis] = sliceIdx;
    setCursor(ijkToWorld(g0, ijk));
  }

  function moveSlice(steps: number): void {
    if (!cursorIjk) return;
    const ijk: Vec3 = [...cursorIjk] as Vec3;
    ijk[basis.sliceAxis] = Math.min(nSlices - 1, Math.max(0, sliceIdx + steps));
    setCursor(ijkToWorld(g0, ijk));
  }

  let wheelAcc = 0;
  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    const rect = host!.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) {
      // zoom about the mouse: the plane point under it stays put
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const [pu, pv] = fromScreen(mx, my);
      scale = Math.min(fit * 40, Math.max(fit * 0.25, pxPerMm * Math.exp(-e.deltaY * 0.01)));
      const k = pxPerMm; // after the scale update (derived)
      setCenter(pu - (signU * (mx - W / 2)) / (k * su), pv - (signV * (my - H / 2)) / (k * sv));
      return;
    }
    // line-mode wheels report ~1–3 per notch, pixel-mode trackpads ~4–100 per event
    wheelAcc += e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
    const steps = Math.trunc(wheelAcc / 33);
    if (steps) {
      wheelAcc -= steps * 33;
      moveSlice(-steps * basis.sliceSign);
    }
  }

  type Drag = { mode: "cursor" | "wl" | "pan" | "paint"; x: number; y: number; c: number; w: number; cu: number; cv: number };

  // painting: the stroke in progress + committed strokes the shown result doesn't contain
  // yet (layers.pending) are drawn instantly — into the overlay itself when there is one
  let strokeTick = $state(0);
  let painting: Stroke | null = null;
  const liveStrokes = (): Stroke[] => (painting ? [...layers.pending, painting] : layers.pending);
  let editBuf = new Uint8Array(0);
  let editApplied = false; // strokes went into the overlay this frame (no canvas disks)
  function paintAt(x: number, y: number): void {
    if (!painting) return;
    const w = worldAt(x, y);
    const last = painting.p[painting.p.length - 1];
    if (last && Math.hypot(w[0] - last[0], w[1] - last[1], w[2] - last[2]) < painting.r / 3) return;
    painting.p.push(w);
    strokeTick++;
  }
  let drag = $state<Drag | null>(null);

  function onDown(e: PointerEvent): void {
    const rect = host!.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const tool = e.button === 0 && !e.shiftKey ? layers.tool : null;
    if (tool === "seed") {
      layers.onSeed?.(worldAt(x, y));
      return;
    }
    const mode: Drag["mode"] = tool
      ? "paint"
      : e.button === 2
        ? "wl"
        : e.button === 1 || (e.button === 0 && e.shiftKey)
          ? "pan"
          : "cursor";
    host!.setPointerCapture(e.pointerId);
    drag = { mode, x: e.clientX, y: e.clientY, c: scene.wl?.center ?? 0, w: scene.wl?.width ?? 1, cu, cv };
    if (mode === "cursor") cursorAt(x, y);
    if (mode === "paint") {
      painting = { p: [], r: layers.brushR, mode: tool === "erase" ? "erase" : "add" };
      paintAt(x, y);
    }
  }

  let hover = $state<{ x: number; y: number } | null>(null);
  function onMove(e: PointerEvent): void {
    const rect = host!.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    hover = { x, y };
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (drag.mode === "cursor") cursorAt(x, y);
    else if (drag.mode === "paint") paintAt(x, y);
    else if (drag.mode === "wl") {
      const k = Math.max(0.5, drag.w / 300);
      setWL({ center: drag.c - dy * k, width: Math.max(1, drag.w + dx * k * 2) });
    } else {
      setCenter(drag.cu - (signU * dx) / (pxPerMm * su), drag.cv - (signV * dy) / (pxPerMm * sv));
    }
  }
  function onUp(): void {
    if (drag?.mode === "paint" && painting && painting.p.length) layers.onStroke?.({ ...painting });
    painting = null;
    drag = null;
  }

  // ── slice slider (header strip) ─────────────────────────────────────────────
  let track = $state<HTMLDivElement>();
  let sliding = $state(false);
  function slideTo(e: PointerEvent): void {
    if (!track || !cursorIjk) return;
    const r = track.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const ijk: Vec3 = [...cursorIjk] as Vec3;
    ijk[basis.sliceAxis] = Math.round(f * (nSlices - 1));
    setCursor(ijkToWorld(g0, ijk));
  }
  function onSliderDown(e: PointerEvent): void {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    sliding = true;
    slideTo(e);
  }
  function onSliderMove(e: PointerEvent): void {
    if (sliding) slideTo(e);
  }

  /** Voxel value under the mouse, read from the slice already on the GPU's CPU twin. */
  const probe = $derived.by(() => {
    if (!hover || !shown) return null;
    const m = screenToTex(shown.req.level);
    const xd = hover.x * dpr;
    const yd = hover.y * dpr;
    const tx = Math.floor(m[0] * xd + m[1] * yd + m[2]);
    const ty = Math.floor(m[3] * xd + m[4] * yd + m[5]);
    const s = shown.slice;
    if (tx < 0 || ty < 0 || tx >= s.cols || ty >= s.rows) return null;
    const [iu, iv] = fromScreen(hover.x, hover.y);
    const ijk: Vec3 = [0, 0, 0];
    ijk[basis.uAxis] = iu;
    ijk[basis.vAxis] = iv;
    ijk[basis.sliceAxis] = sliceIdx;
    return { value: s.data[ty * s.cols + tx], world: ijkToWorld(g0, ijk) };
  });

  const letters = $derived(edgeLetters(plane));
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="view"
  class:tool-seed={layers.tool === "seed"}
  class:tool-brush={layers.tool === "brush" || layers.tool === "erase"}
  bind:this={host}
  style:--plane={PLANE_COLOR[plane]}
  onwheel={onWheel}
  onpointerdown={onDown}
  onpointermove={onMove}
  onpointerup={onUp}
  onpointercancel={onUp}
  onpointerleave={() => (hover = null)}
  ondblclick={() => !layers.tool && toggleMaximized(plane)}
  oncontextmenu={(e) => e.preventDefault()}
>
  <canvas class="gl" bind:this={glCanvas} style:width="{W}px" style:height="{H}px"></canvas>
  <canvas class="ov" bind:this={overlay} style:width="{W}px" style:height="{H}px"></canvas>
  {#if shown}<MarkupLayer2D {proj} {layers} />{/if}

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="head" onpointerdown={(e) => e.stopPropagation()} ondblclick={(e) => e.stopPropagation()}>
    <span class="pdot" title={PLANE_LABEL[plane]}></span>
    <div
      class="track"
      class:sliding
      bind:this={track}
      title="Przeciągnij, aby przewijać warstwy"
      onpointerdown={onSliderDown}
      onpointermove={onSliderMove}
      onpointerup={() => (sliding = false)}
      onpointercancel={() => (sliding = false)}
    >
      <div class="rail"><div class="fill" style:width="{(sliceIdx / Math.max(1, nSlices - 1)) * 100}%"></div></div>
      <div class="thumb" style:left="{(sliceIdx / Math.max(1, nSlices - 1)) * 100}%"></div>
    </div>
    <span class="idx">{sliceIdx + 1}<i>/{nSlices}</i></span>
  </div>
  {#if drag?.mode === "wl" && scene.wl}
    <div class="wlhud">O {num(scene.wl.center, 0)} · S {num(scene.wl.width, 0)}</div>
  {/if}
  {#if showLoading}
    <div class="loading" class:center={!shown}><ProgressRing size={shown ? 20 : 40} /></div>
  {/if}
  {#if probe}
    <div class="hud bl">
      {probe.world.map((c) => num(c, 1)).join(", ")} mm · <b>{num(probe.value, 1)}</b>
    </div>
  {/if}
  {#if shown && shown.req.level > 0}<div class="hud br">poziom {shown.req.level}</div>{/if}
  <span class="edge l">{letters[0]}</span>
  <span class="edge r">{letters[1]}</span>
  <span class="edge t">{letters[2]}</span>
  <span class="edge b">{letters[3]}</span>
  {#if glError || loadError}<div class="err">{glError || loadError}</div>{/if}
</div>

<style>
  .view {
    position: relative;
    width: 100%;
    height: 100%;
    background: #000;
    overflow: hidden;
    cursor: crosshair;
    touch-action: none;
    border: 1px solid transparent;
    border-top: 2px solid var(--plane);
  }
  canvas {
    position: absolute;
    left: 0;
    top: 0;
    display: block;
  }
  .ov {
    pointer-events: none;
  }
  .view.tool-seed {
    cursor: cell;
  }
  .view.tool-brush {
    cursor: none;
  }
  .hud {
    position: absolute;
    font-size: var(--fs-xs);
    color: rgba(255, 255, 255, 0.75);
    text-shadow: 0 1px 2px #000;
    pointer-events: none;
    white-space: nowrap;
  }
  .hud b {
    color: var(--plane);
    font-weight: 600;
  }
  .bl b {
    color: var(--accent);
  }
  .head {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 22px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 8px;
    background: linear-gradient(rgba(0, 0, 0, 0.65), rgba(0, 0, 0, 0));
    z-index: 2;
    cursor: default;
  }
  .pdot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--plane);
    flex-shrink: 0;
  }
  .track {
    position: relative;
    flex: 1;
    height: 16px;
    cursor: pointer;
    touch-action: none;
  }
  .rail {
    position: absolute;
    left: 0;
    right: 0;
    top: 7px;
    height: 2px;
    border-radius: 1px;
    background: rgba(255, 255, 255, 0.14);
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--plane);
    opacity: 0.55;
  }
  .thumb {
    position: absolute;
    top: 3px;
    width: 10px;
    height: 10px;
    margin-left: -5px;
    border-radius: 50%;
    background: var(--plane);
    box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.6);
    transition: transform 0.1s;
  }
  .track:hover .thumb,
  .track.sliding .thumb {
    transform: scale(1.3);
  }
  .idx {
    font-size: var(--fs-xs);
    color: rgba(255, 255, 255, 0.8);
    min-width: 54px;
    text-align: right;
  }
  .idx i {
    font-style: normal;
    color: rgba(255, 255, 255, 0.35);
  }
  .wlhud {
    position: absolute;
    top: 28px;
    left: 50%;
    transform: translateX(-50%);
    padding: 2px 8px;
    font-size: var(--fs-xs);
    color: var(--accent);
    background: rgba(0, 0, 0, 0.6);
    border-radius: 10px;
    pointer-events: none;
  }
  .loading {
    position: absolute;
    top: 28px;
    right: 8px;
    pointer-events: none;
  }
  .loading.center {
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .bl {
    bottom: 6px;
    left: 8px;
  }
  .br {
    bottom: 6px;
    right: 8px;
    color: var(--text-dim-3);
  }
  .edge {
    position: absolute;
    font-size: var(--fs-xs);
    font-weight: 600;
    color: rgba(255, 255, 255, 0.45);
    pointer-events: none;
  }
  .edge.l {
    left: 6px;
    top: 50%;
    transform: translateY(-50%);
  }
  .edge.r {
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
  }
  .edge.t {
    top: 28px;
    left: 50%;
    transform: translateX(-50%);
  }
  .edge.b {
    bottom: 22px;
    left: 50%;
    transform: translateX(-50%);
  }
  .err {
    position: absolute;
    inset: auto 8px 28px 8px;
    font-size: var(--fs-xs);
    color: var(--danger);
  }
</style>
