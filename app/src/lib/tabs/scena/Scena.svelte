<script lang="ts">
  import {
    libraryLoaded,
    libraryVolumes,
    volumeMeta,
    type VolumeEntry,
    type VolumeMeta,
  } from "#lib/core/library.svelte.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { bestRun, startEvaluation, VOLUME_KINDS, type MeshOut, type VolumeOut } from "#lib/graph/evaluation.svelte.ts";
  import GraphEditor from "#lib/graph/GraphEditor.svelte";
  import CropModal from "#lib/graph/CropModal.svelte";
  import TableModal from "#lib/graph/TableModal.svelte";
  import { segTools, setBrushR, setTool } from "#lib/graph/segTools.svelte.ts";
  import { commit, undo, redo } from "#lib/graph/store.svelte.ts";
  import { NO_LAYERS, type OverlaySpec, type SliceLayers, type Stroke } from "#lib/viewport/layers.ts";
  import type { Vec3 } from "#lib/viewport/geometry.ts";
  import { loadNodeTypes, nodeType } from "#lib/graph/registry.svelte.ts";
  import { graph, loadGraphs, nodeById } from "#lib/graph/store.svelte.ts";
  import { bindVolume, requestFocus, scene } from "#lib/viewport/scene.svelte.ts";
  import ViewportGrid from "#lib/viewport/ViewportGrid.svelte";
  import ScenePanel from "./ScenePanel.svelte";
  import type { Markup } from "#lib/viewport/markups.ts";
  import { cancelDraft, markupDraft } from "#lib/viewport/markupDraft.svelte.ts";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { upstreamVolume } from "#lib/graph/upstream.ts";
  import { getSetting } from "#lib/core/appSettings.svelte.ts";
  import { untrack } from "svelte";

  let error = $state("");

  // Graph: node types + graphs of this workspace, then live evaluation.
  $effect(() => {
    Promise.all([loadNodeTypes(), loadGraphs()]).catch((e) => (error = String(e?.message ?? e)));
    return startEvaluation();
  });

  // What the viewports show: the visible layers (nodes with the eye on, top first).
  // displayNode = the active layer (or the topmost visible one): tools and status follow it.
  const visibleLayers = $derived(
    (graph.doc.layers ?? []).flatMap((l) => {
      const n = l.hidden ? undefined : nodeById(l.node);
      return n ? [n] : [];
    }),
  );
  const displayNode = $derived(visibleLayers.find((n) => n.id === graph.doc.display) ?? visibleLayers[0]);
  const displayRun = $derived(displayNode ? bestRun(displayNode.id) : null);
  const volOutOf = (id: string) => {
    const r = bestRun(id);
    const o = r?.outputs ? Object.values(r.outputs).find((v) => VOLUME_KINDS.includes(v.kind)) : undefined;
    return (o as VolumeOut | undefined) ?? null;
  };
  const meshOutOf = (id: string) => {
    const r = bestRun(id);
    const o = r?.outputs ? Object.values(r.outputs).find((v) => v.kind === "mesh") : undefined;
    return (o as MeshOut | undefined) ?? null;
  };
  const keyOf = (id: string) => `node:${graph.activeId}:${id}`;
  const nodeOut = $derived(displayNode ? volOutOf(displayNode.id) : null);
  // a mesh node: the surface in every view, over its background volume (info.ref) or, for an
  // imported file without one, over whatever is already shown
  const meshOut = $derived(displayNode ? meshOutOf(displayNode.id) : null);
  const isLabel = (o: VolumeOut | null) => !!o && (o.kind === "segment" || o.kind === "segmentacja");
  // background = the active layer if it is a plain volume, else the topmost visible volume
  // layer — a segmentation is then drawn over THAT volume (placed in world space)
  const baseNode = $derived(
    [displayNode, ...visibleLayers].find((n) => n && volOutOf(n.id)?.kind === "wolumen"),
  );
  // overlay = the active layer if it is a segment(ation), else the topmost visible one
  const ovNode = $derived(
    isLabel(nodeOut) ? displayNode : visibleLayers.find((n) => isLabel(volOutOf(n.id))),
  );
  const meshLayers = $derived(visibleLayers.flatMap((n) => {
    const m = meshOutOf(n.id);
    return m ? [m] : [];
  }));
  const bgOf = (o: VolumeOut) => (isLabel(o) ? (o.info.ref as string) : o.ref);
  // no result (error, missing seeds, first run): show what flows INTO the node, so its
  // tools (seeds, brush) have something to click on
  const nodeIn = $derived.by(() => {
    if (!displayNode || nodeOut || meshOut) return null;
    for (const port of nodeType(displayNode.type)?.inputs ?? []) {
      const o = upstreamVolume(displayNode.id, port.id);
      if (o) return o;
    }
    return null;
  });
  const target = $derived.by(() => {
    const bo = baseNode ? volOutOf(baseNode.id) : null;
    if (baseNode && bo) return { ref: bo.ref, key: keyOf(baseNode.id), out: bo };
    if (displayNode) {
      const key = `node:${graph.activeId}:${displayNode.id}`;
      if (meshOut && !nodeOut) {
        const ref = meshOut.info.ref || untrack(() => shown)?.vol.id;
        return ref ? { ref, key, out: null } : null;
      }
      const src = nodeOut ?? nodeIn;
      if (!src) return null;
      let ref = bgOf(src);
      // A preview segment sits on the PREVIEW of its input (e.g. a preview crop) — another
      // volume than the full one. Keep the background already shown for this node: the
      // overlay is placed in world space, and the 3-D volume isn't swapped on every edit.
      const cur = untrack(() => shown);
      if (isLabel(src) && displayRun?.quality !== "full" && cur?.key === key && getSetting("graphAutoFull", true))
        ref = cur.vol.id;
      return ref ? { ref, key, out: nodeOut } : null;
    }
    return null;
  });

  // overlay spec (label volume + colours) for a displayed segment / segmentation
  let overlay = $state.raw<OverlaySpec | null>(null);
  $effect(() => {
    const o = ovNode ? volOutOf(ovNode.id) : null;
    const full = ovNode ? bestRun(ovNode.id)?.quality === "full" : false;
    const key = ovNode ? keyOf(ovNode.id) : "";
    if (!o || !isLabel(o)) {
      overlay = null;
      return;
    }
    const cur = untrack(() => overlay);
    if (cur?.ref === o.ref) return;
    // A full-resolution mask of this node stays while a coarse preview of the next result
    // stands in: the preview's blocky voxels looked like leftovers after erasing. Strokes
    // not in the shown result are drawn as pending meanwhile.
    if (!full && cur?.full && cur.key === key && getSetting("graphAutoFull", true)) return;
    const ctl = new AbortController();
    volumeMeta(o.ref, ctl.signal)
      .then((m) => {
        const colors: Record<number, string> =
          o.kind === "segmentacja"
            ? Object.fromEntries(((o.info.labels as { id: number; color: string }[]) ?? []).map((l) => [l.id, l.color]))
            : { 1: (o.info.color as string) ?? "#7bc47f" };
        overlay = { ref: o.ref, meta: m, colors, full, key, node: ovNode?.id, strokes: o.info.strokes as number | undefined };
      })
      .catch(() => {});
    return () => ctl.abort();
  });

  // segmentation tools → node params (one undo step per seed / stroke)
  const toolNode = $derived(segTools.nodeId ? nodeById(segTools.nodeId) : undefined);
  $effect(() => {
    if (segTools.tool && !toolNode) setTool(null); // node deleted
  });
  function onSeed(w: Vec3): void {
    if (!toolNode) return;
    toolNode.params.seeds = [...((toolNode.params.seeds as Vec3[]) ?? []), w.map((c) => Math.round(c * 1000) / 1000)];
    commit();
  }
  function onStroke(st: Stroke): void {
    if (!toolNode) return;
    toolNode.params.strokes = [...((toolNode.params.strokes as Stroke[]) ?? []), st];
    commit();
  }

  // brush strokes of the displayed edit node that its shown result doesn't contain yet
  const pending = $derived.by<Stroke[]>(() => {
    if (displayNode?.type !== "segmentacja/edycja") return [];
    const all = (displayNode.params.strokes as Stroke[]) ?? [];
    const n = overlay?.key === `node:${graph.activeId}:${displayNode.id}` ? (overlay.strokes ?? 0) : 0;
    return n >= all.length ? [] : all.slice(n);
  });

  // markups of every Markupy node: always drawn, edited in place (one undo step per gesture)
  const markups = $derived(
    graph.doc.nodes
      .filter((n) => n.type === "pomiary/markupy")
      .map((n) => ({ nodeId: n.id, items: (n.params.items as Markup[]) ?? [] })),
  );
  function onMarkups(nodeId: string, items: Markup[]): void {
    const n = nodeById(nodeId);
    if (!n) return;
    n.params.items = items;
    commit();
  }

  // the other visible segment layers (shown together with the editable overlay)
  const extraSrc = $derived(
    visibleLayers.flatMap((n) => {
      const o = n.id === ovNode?.id ? null : volOutOf(n.id);
      return o && isLabel(o) ? [{ node: n.id, o }] : [];
    }),
  );
  let extraOverlays = $state.raw<OverlaySpec[]>([]);
  // run-state churn re-derives `extraSrc`; only a change of what is shown reloads anything
  const extraSig = $derived(JSON.stringify(extraSrc.map((e) => [e.node, e.o.ref, e.o.info.labels ?? e.o.info.color ?? null])));
  $effect(() => {
    void extraSig;
    const src = untrack(() => extraSrc);
    if (!src.length) {
      if (untrack(() => extraOverlays).length) extraOverlays = [];
      return;
    }
    const ctl = new AbortController();
    Promise.all(
      src.map(async ({ node, o }) => {
        const m = await volumeMeta(o.ref, ctl.signal);
        const colors: Record<number, string> =
          o.kind === "segmentacja"
            ? Object.fromEntries(((o.info.labels as { id: number; color: string }[]) ?? []).map((l) => [l.id, l.color]))
            : { 1: (o.info.color as string) ?? "#7bc47f" };
        return { ref: o.ref, meta: m, colors, node, key: keyOf(node) } satisfies OverlaySpec;
      }),
    )
      .then((list) => !ctl.signal.aborted && (extraOverlays = list))
      .catch(() => {});
    return () => ctl.abort();
  });
  // bottom → top, each with the colour picked on its layer
  const shownExtras = $derived(
    [...extraOverlays].reverse().map((o) => {
      const c = (graph.doc.layers ?? []).find((l) => l.node === o.node)?.color;
      return c && Object.keys(o.colors).length <= 1 ? { ...o, colors: { 1: c } } : o;
    }),
  );

  // a colour picked on the layer wins over the node's own (single segments only)
  const layerColor = $derived((graph.doc.layers ?? []).find((l) => l.node === ovNode?.id)?.color);
  const shownOverlay = $derived(
    overlay && layerColor && Object.keys(overlay.colors).length <= 1 ? { ...overlay, colors: { 1: layerColor } } : overlay,
  );

  const layers = $derived.by<SliceLayers>(() => {
    const thr =
      displayNode?.type === "segmentacja/prog"
        ? { lo: Number(displayNode.params.lo), hi: Number(displayNode.params.hi), color: layerColor ?? "#7bc47f", node: displayNode.id }
        : null;
    const color = layerColor ?? (nodeOut?.info?.color as string) ?? "#7bc47f";
    return {
      ...NO_LAYERS,
      overlay: shownOverlay,
      extras: shownExtras,
      // threshold node: the 2-D views show the live threshold (exact, 60 fps) instead of a
      // possibly stale mask; the 3-D view keeps the computed mask
      threshold: thr,
      alpha: scene.overlayAlpha,
      outline: scene.overlayOutline,
      tool: toolNode ? segTools.tool : null,
      brushR: segTools.brushR,
      cut: segTools.cut,
      pending,
      seeds: toolNode?.type === "segmentacja/rozrost" ? ((toolNode.params.seeds as Vec3[]) ?? []) : [],
      color,
      onSeed,
      onStroke,
      toolNode: toolNode?.id ?? null,
      markups,
      focusMarkup: segTools.focusMarkup,
      onMarkups,
      meshes: meshLayers.map((m) => ({ ref: m.ref, color: m.info.color ?? "#4db6ac", name: m.info.name ?? "Mesh" })),
      meshOpacity: scene.meshOpacity,
    };
  });

  /** Library entry, or an entry synthesised from a node result's stored metadata. */
  function entryFor(ref: string, m: VolumeMeta & { info?: VolumeOut["info"]; planes?: VolumeEntry["planes"] }): VolumeEntry {
    const lib = libraryVolumes().find((v) => v.id === ref);
    if (lib) return lib;
    const g0 = m.levels[0];
    const info = m.info ?? {};
    const st = m.stats;
    return {
      id: ref,
      name: info.name ?? "Wynik",
      kind: "scalar",
      source: "dicom",
      sourcePath: null,
      anonymized: true,
      createdAt: "",
      size: g0.size,
      spacing: g0.spacing,
      dtype: m.dtype,
      levels: m.levels.length,
      bytesOnDisk: 0,
      window: info.window ?? { center: (st.p1 + st.p99) / 2, width: Math.max(1, st.p99 - st.p1) },
      stats: { min: st.min, max: st.max, p1: st.p1, p99: st.p99 },
      planes: m.planes ?? { i: "strzałkowy", j: "czołowy", k: "osiowy" },
      warnings: [],
      importSeconds: 0,
      modality: info.modality,
    };
  }

  let shown = $state.raw<{ vol: VolumeEntry; meta: VolumeMeta; key: string } | null>(null);
  $effect(() => {
    const t = target;
    if (!t) {
      shown = null; // last layer removed / hidden: empty scene
      return;
    }
    if (shown && shown.vol.id === t.ref && shown.key === t.key) return;
    const ctl = new AbortController();
    error = "";
    volumeMeta(t.ref, ctl.signal)
      .then((m) => {
        const vol = entryFor(t.ref, m as VolumeMeta & { info?: VolumeOut["info"] });
        bindVolume(vol, m, t.key);
        shown = { vol, meta: m, key: t.key };
      })
      .catch((e) => !ctl.signal.aborted && (error = String(e?.message ?? e)));
    return () => ctl.abort();
  });

  // what the badge over the views says about the displayed node
  const nodeStatus = $derived.by<{ kind: "busy" | "error"; text: string } | null>(() => {
    if (!displayNode) return null;
    const st = displayRun?.state;
    const out = nodeOut ?? meshOut;
    if ((st === "error" || st === "blocked") && !out) return { kind: "error", text: displayRun?.error ?? "Błąd" };
    if (!out || st === "computing" || (shown && target && shown.key !== target.key))
      return { kind: "busy", text: `Liczenie: ${displayLabel}…` };
    return null;
  });
  const displayQuality = $derived(displayNode ? (bestRun(displayNode.id)?.quality ?? null) : null);
  const displayLabel = $derived(displayNode ? (nodeType(displayNode.type)?.label ?? "") : "");

  // Maximised area (Blender's Ctrl+Space): null | "graph" | "views". Hidden areas stay
  // mounted (CSS only), so going back never reloads the 3-D volume.
  type Area = "graph" | "views";
  let maxArea = $state<Area | null>(wsGet<Area | null>("scena_maxArea", null));
  let hoverArea: Area | null = null;
  function toggleMax(a: Area): void {
    maxArea = maxArea === a ? null : a;
    wsSet("scena_maxArea", maxArea);
  }
  function onKey(e: KeyboardEvent): void {
    const t = e.target as HTMLElement;
    const typing = t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT";
    const inGraph = !!t.closest?.(".canvas");
    if (!typing && segTools.tool) {
      if (e.key === "Escape") {
        if (markupDraft.draft) cancelDraft(); // first Esc: the unfinished markup only
        else setTool(null);
      }
      else if (e.key === "[") setBrushR(segTools.brushR / 1.25);
      else if (e.key === "]") setBrushR(segTools.brushR * 1.25);
    }
    // undo/redo outside the graph editor too (e.g. right after painting in a view)
    if (!typing && !inGraph && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    }
    if (!typing && !inGraph && hoverArea === "views" && !e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "f") {
      e.preventDefault();
      requestFocus();
    }
    if (e.code === "Space" && e.ctrlKey && hoverArea) {
      e.preventDefault();
      e.stopPropagation();
      toggleMax(maxArea ?? hoverArea);
    }
  }

  // Splitter between viewports and the graph editor; height remembered per workspace.
  let graphH = $state(wsGet<number>("scena_graphHeight", 300));
  let split = $state<HTMLDivElement>();
  let dragging = false;
  function onSplitDown(e: PointerEvent): void {
    dragging = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onSplitMove(e: PointerEvent): void {
    if (!dragging || !split) return;
    const r = split.getBoundingClientRect();
    graphH = Math.min(r.height - 160, Math.max(60, r.bottom - e.clientY));
  }
  function onSplitUp(): void {
    if (!dragging) return;
    dragging = false;
    wsSet("scena_graphHeight", Math.round(graphH));
  }
</script>

<svelte:window onkeydowncapture={onKey} />

<div class="scena">
  <div class="main" bind:this={split}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="views" class:gone={maxArea === "graph"} onpointerenter={() => (hoverArea = "views")}>
      {#if shown && scene.meta}
        <ViewportGrid vol={shown.vol} meta={scene.meta} frameKey={shown.key} {layers} />
        {#if nodeStatus?.kind === "error" && displayNode && nodeType(displayNode.type)?.widget === "seeds" && !segTools.tool}
          <!-- no seeds yet: the badge itself starts the seed tool -->
          <button class="badge err act" onclick={() => displayNode && setTool("seed", displayNode.id)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor" /><path d="M12 2v5M12 17v5M2 12h5M17 12h5" /></svg>
            Kliknij tu, potem ziarno w widoku 2D
          </button>
        {:else if nodeStatus?.kind === "error"}
          <div class="badge err"><Icon name="alert" size={13} />{nodeStatus.text}</div>
        {:else if nodeStatus}
          <div class="badge"><ProgressRing size={14} />{nodeStatus.text}</div>
        {:else if displayQuality === "preview"}
          <div class="badge soft">Podgląd · pełna rozdzielczość w drodze</div>
        {/if}
      {:else if libraryLoaded() && !libraryVolumes().length}
        <div class="empty">
          <Icon name="cube" size={34} />
          <span>Brak wolumenów — zaimportuj serię w zakładce Dane.</span>
        </div>
      {:else if graph.loaded && !visibleLayers.length}
        <div class="empty">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>
          <span>Scena jest pusta — włącz oczko na karcie w grafie.</span>
        </div>
      {:else if error}
        <div class="empty err">{error}</div>
      {/if}
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="splitter"
      class:gone={maxArea !== null}
      onpointerdown={onSplitDown}
      onpointermove={onSplitMove}
      onpointerup={onSplitUp}
      onpointercancel={onSplitUp}
      ondblclick={() => toggleMax("graph")}
    >
      <div class="sbtns" onpointerdown={(e) => e.stopPropagation()}>
        <button title="Widoki na cały ekran (Ctrl+Spacja nad widokami)" onclick={() => toggleMax("views")}>▾</button>
        <button title="Graf na cały ekran (Ctrl+Spacja nad grafem)" onclick={() => toggleMax("graph")}>▴</button>
      </div>
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="graph"
      class:gone={maxArea === "views"}
      class:full={maxArea === "graph"}
      style:height={maxArea === "graph" ? null : `${graphH}px`}
      onpointerenter={() => (hoverArea = "graph")}
    >
      {#if graph.loaded}
        <svelte:boundary>
          <GraphEditor maximized={maxArea === "graph"} onmax={() => toggleMax("graph")} />
          {#snippet failed(error, reset)}
            <div class="empty err">
              {(error as Error)?.message ?? String(error)}
              <button class="btn" onclick={reset}>Odśwież edytor</button>
            </div>
          {/snippet}
        </svelte:boundary>
      {/if}
    </div>
  </div>
  <ScenePanel
    vol={shown?.vol}
    roles={{ base: shown ? (baseNode?.id ?? (displayNode && !isLabel(nodeOut) && !meshOut ? displayNode.id : null)) : null, overlay: overlay ? (ovNode?.id ?? null) : null, extra: extraOverlays.map((o) => o.node ?? "") }}
    hasOverlay={!!overlay || extraOverlays.length > 0}
    hasMesh={meshLayers.length > 0}
  />
  <CropModal />
  <TableModal />
  {#if maxArea}
    <button class="restore" title="Przywróć układ (Ctrl+Spacja)" onclick={() => toggleMax(maxArea!)}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" /></svg>
    </button>
  {/if}
</div>

<style>
  .scena {
    position: relative;
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
  }
  .main {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .views {
    flex: 1;
    min-height: 0;
    position: relative;
    background: var(--bg-deepest);
  }
  .splitter {
    height: 6px;
    flex-shrink: 0;
    cursor: row-resize;
    background: var(--bg-panel);
    border-top: 1px solid var(--line-1);
    border-bottom: 1px solid var(--line-1);
  }
  .splitter {
    position: relative;
  }
  .splitter:hover {
    background: var(--accent-a15);
  }
  .sbtns {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    gap: 2px;
    opacity: 0.55;
    transition: opacity 0.15s;
  }
  .splitter:hover .sbtns {
    opacity: 1;
  }
  .sbtns button {
    width: 26px;
    height: 14px;
    padding: 0;
    font-size: 0.6rem;
    line-height: 1;
    color: var(--text-dim-1);
    background: var(--bg-panel-2);
    border: 1px solid var(--line-2);
    border-radius: 4px;
    cursor: pointer;
  }
  .sbtns button:hover {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
  .gone {
    display: none !important;
  }
  .graph.full {
    flex: 1;
  }
  .restore {
    position: absolute;
    right: 282px;
    bottom: 12px;
    z-index: 40;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--accent);
    background: var(--bg-panel);
    border: 1px solid var(--accent-a40);
    border-radius: 50%;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
    cursor: pointer;
  }
  .graph {
    flex-shrink: 0;
    display: flex;
    min-height: 0;
    background: var(--bg-deep);
  }
  .badge {
    position: absolute;
    top: 30px;
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 12px;
    font-size: var(--fs-xs);
    color: var(--accent);
    background: var(--bg-panel);
    border: 1px solid var(--accent-a30);
    border-radius: 12px;
    pointer-events: none;
    display: flex;
    align-items: center;
    gap: 6px;
    max-width: 80%;
  }
  .badge.err {
    color: var(--warn, #f2c94c);
    border-color: rgba(242, 201, 76, 0.45);
  }
  .badge.act {
    pointer-events: auto;
    cursor: pointer;
    font: inherit;
    font-size: var(--fs-xs);
  }
  .badge.act:hover {
    background: rgba(242, 201, 76, 0.12);
  }
  .badge.soft {
    color: var(--text-dim-1);
    border-color: var(--line-2);
  }
  .empty {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-sm);
    color: var(--text-dim-3);
  }
  .err {
    color: var(--danger);
  }
</style>
