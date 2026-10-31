<script lang="ts">
  // Scene sidebar — visual first: thumbnails, layout icons, the window drawn on the
  // histogram, colour swatches for 3-D presets. Explanations live in tooltips.
  import type { VolumeEntry } from "#lib/core/library.svelte.ts";
  import { num } from "#lib/ui/format.ts";
  import { graph, moveLayer, nodeById, select, setDisplay, setLayerColor, setLayerHidden, toggleLayer } from "#lib/graph/store.svelte.ts";
  import { bestRun } from "#lib/graph/evaluation.svelte.ts";
  import { PORT_COLORS, type PortKind } from "#lib/graph/types.ts";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { autoWindow, buildTf, CT_WINDOWS, tfPresetsFor, type TfPresetId } from "#lib/viewport/presets.ts";
  import {
    scene,
    setLayout,
    setSingle,
    setTf,
    setWL,
    setOverlayStyle,
    setMeshOpacity,
    type Layout,
    type ViewId,
  } from "#lib/viewport/scene.svelte.ts";
  import WindowHistogram from "./WindowHistogram.svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import { copyValue } from "#lib/core/notePad.svelte.ts";
  import { nodeType } from "#lib/graph/registry.svelte.ts";
  import TableChart from "#lib/graph/TableChart.svelte";
  import { openTable, tableOf } from "#lib/graph/tableView.svelte.ts";

  let {
    vol,
    roles,
    hasOverlay = false,
    hasMesh = false,
  }: {
    vol: VolumeEntry | undefined;
    roles: { base: string | null; overlay: string | null; extra: string[] };
    hasOverlay?: boolean;
    hasMesh?: boolean;
  } = $props();

  // one row per layer: what it is (colour of its output kind) and what it does on the scene
  const layerRows = $derived(
    (graph.doc.layers ?? []).flatMap((l) => {
      const node = nodeById(l.node);
      if (!node) return [];
      const run = bestRun(node.id);
      const out = run?.outputs ? Object.values(run.outputs).find((v) => v.kind in PORT_COLORS && v.kind !== "tabela") : undefined;
      const kind = (out?.kind as PortKind | undefined) ?? nodeType(node.type)?.outputs[0]?.kind;
      const role = l.hidden
        ? ""
        : node.id === roles.base
          ? "tło"
          : node.id === roles.overlay || roles.extra.includes(node.id)
            ? "nakładka"
            : kind === "mesh" && out
              ? "powierzchnia"
              : "";
      return [{
        id: node.id,
        label: nodeType(node.type)?.label ?? node.type,
        color: kind ? PORT_COLORS[kind] : "var(--text-dim-3)",
        hidden: !!l.hidden,
        // pickable for a single segment (a multi-label map has a colour per label)
        pick: kind === "segment" ? (l.color ?? ((out as { info?: { color?: string } } | undefined)?.info?.color) ?? "#7bc47f") : null,
        role,
        busy: run?.state === "computing",
      }];
    }),
  );

  // reorder by dragging the grip (Pointer Events; rows have a fixed height)
  const ROW_H = 36;
  let drag = $state<{ id: string; from: number; y0: number; dy: number } | null>(null);
  function onGripDown(e: PointerEvent, id: string, n: number): void {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag = { id, from: n, y0: e.clientY, dy: 0 };
  }
  function onGripMove(e: PointerEvent): void {
    if (drag) drag.dy = e.clientY - drag.y0;
  }
  function onGripUp(): void {
    if (!drag) return;
    const to = drag.from + Math.round(drag.dy / ROW_H);
    const { id, from } = drag;
    drag = null;
    if (to !== from) moveLayer(id, to);
  }

  // results of every measurement node, at a glance (click → full table + CSV)
  const results = $derived(
    graph.doc.nodes.flatMap((n) => {
      const t = nodeType(n.type);
      const port = t?.outputs.find((o) => o.kind === "tabela");
      const v = port ? tableOf(n.id, port.id) : null;
      return t && port && v && v.rows.length ? [{ id: n.id, port: port.id, label: t.label, v }] : [];
    }),
  );


  const LAYOUTS: { id: Layout; title: string; cells: [number, number, number, number, boolean][] }[] = [
    { id: "quad", title: "2 × 2", cells: [[0, 0, 9, 7, false], [10, 0, 9, 7, true], [0, 8, 9, 7, false], [10, 8, 9, 7, false]] },
    { id: "main3d", title: "3D + 3 przekroje", cells: [[0, 0, 12, 15, true], [13, 0, 6, 4.3, false], [13, 5.3, 6, 4.3, false], [13, 10.6, 6, 4.4, false]] },
    { id: "single", title: "Jeden widok", cells: [[0, 0, 19, 15, false]] },
  ];
  const SINGLE: { id: ViewId; label: string; color: string }[] = [
    { id: "axial", label: "Ax", color: "#e05a5a" },
    { id: "coronal", label: "Co", color: "#6cbf6c" },
    { id: "sagittal", label: "Sa", color: "#e8c547" },
    { id: "3d", label: "3D", color: "#5b9bd5" },
  ];

  const TF_SHORT: Record<TfPresetId, string> = {
    "ct-angio": "Naczynia",
    "ct-bone": "Kości",
    "ct-soft": "Skóra",
    mip: "MIP",
    generic: "Auto",
  };

  /** CSS gradient of a transfer function: colour × opacity across its value span. */
  function swatch(id: TfPresetId): string {
    if (!vol || !scene.wl) return "none";
    const tf = buildTf(id, vol, scene.wl);
    const lo = Math.min(tf.color[0][0], tf.opacity[0][0]);
    const hi = Math.max(tf.color[tf.color.length - 1][0], tf.opacity[tf.opacity.length - 1][0]);
    const lin = <T extends number[]>(pts: T[], x: number, k: number) => {
      if (x <= pts[0][0]) return pts[0][k];
      for (let i = 1; i < pts.length; i++)
        if (x <= pts[i][0]) {
          const t = (x - pts[i - 1][0]) / Math.max(1e-9, pts[i][0] - pts[i - 1][0]);
          return pts[i - 1][k] + t * (pts[i][k] - pts[i - 1][k]);
        }
      return pts[pts.length - 1][k];
    };
    const stops: string[] = [];
    for (let s = 0; s <= 16; s++) {
      const x = lo + ((hi - lo) * s) / 16;
      const a = Math.min(1, lin(tf.opacity, x, 1) * 1.6);
      const [r, g, b] = [1, 2, 3].map((k) => Math.round(lin(tf.color, x, k) * 255));
      stops.push(`rgba(${r},${g},${b},${a.toFixed(2)}) ${(s / 16) * 100}%`);
    }
    return `linear-gradient(90deg, ${stops.join(",")})`;
  }

  const wlPresets = $derived(
    vol
      ? [
          { name: "Seria", wl: vol.window },
          { name: "Auto", wl: autoWindow(vol) },
          ...(vol.modality === "CT" ? CT_WINDOWS.map((p) => ({ name: p.name, wl: { center: p.center, width: p.width } })) : []),
        ]
      : [],
  );
  const isWL = (w: { center: number; width: number }) =>
    !!scene.wl && Math.abs(scene.wl.center - w.center) < 0.5 && Math.abs(scene.wl.width - w.width) < 0.5;
</script>

<div class="panel">
  <!-- layers: nodes with the eye on (top first); drag ⋮⋮ to reorder -->
  <section class="layers">
    <div class="lh"><Icon name="layers" size={13} />Warstwy</div>
    {#each layerRows as r, n (r.id)}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <div
        class="lrow"
        class:active={layerRows.length > 1 && r.id === graph.doc.display}
        class:off={r.hidden || !r.role}
        class:dragging={drag?.id === r.id}
        style:transform={drag?.id === r.id ? `translateY(${drag.dy}px)` : null}
        style:--k={r.color}
        title={r.hidden ? "Ukryta" : r.role ? `${r.role} — kropka: warstwa, którą edytują narzędzia` : "Nieużywana: wyżej jest inna warstwa tego rodzaju"}
        onclick={() => (setDisplay(r.id), select([r.id]))}
      >
        <span class="grip" onpointerdown={(e) => onGripDown(e, r.id, n)} onpointermove={onGripMove} onpointerup={onGripUp} onpointercancel={onGripUp}>⋮⋮</span>
        {#if r.pick}
          <input
            type="color"
            class="pick"
            title="Kolor segmentu"
            value={r.pick}
            onclick={(e) => e.stopPropagation()}
            onchange={(e) => setLayerColor(r.id, e.currentTarget.value)}
          />
        {/if}
        <span class="kind" class:tools={layerRows.length > 1 && r.id === graph.doc.display}></span>
        <span class="lname"><b>{r.label}</b>{#if r.role}<small>{r.role}</small>{/if}</span>
        {#if r.busy}<ProgressRing size={12} />{/if}
        <button
          class="lb"
          class:on={!r.hidden}
          title={r.hidden ? "Pokaż" : "Ukryj"}
          onclick={(e) => (e.stopPropagation(), setLayerHidden(r.id, !r.hidden))}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
            {#if r.hidden}<path d="M3 3l18 18" />{/if}
          </svg>
        </button>
        <button class="lb" title="Usuń ze sceny" onclick={(e) => (e.stopPropagation(), toggleLayer(r.id))}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
    {:else}
      <div class="lempty">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>
        oczko na karcie w grafie
      </div>
    {/each}
  </section>

  <!-- layout -->
  <section>
    <div class="icons">
      {#each LAYOUTS as l (l.id)}
        <button class="ico" class:active={scene.layout === l.id && !scene.maximized} title={l.title} onclick={() => setLayout(l.id)}>
          <svg width="38" height="30" viewBox="-1 -1 21 17">
            {#each l.cells as [x, y, w, h, is3d], n (n)}
              <rect {x} {y} width={w} height={h} rx="1" class:d3={is3d} />
            {/each}
          </svg>
        </button>
      {/each}
    </div>
    {#if scene.layout === "single" && !scene.maximized}
      <div class="icons small">
        {#each SINGLE as v (v.id)}
          <button class="chip" class:active={scene.single === v.id} style:--c={v.color} onclick={() => setSingle(v.id)}>
            {v.label}
          </button>
        {/each}
      </div>
    {/if}
  </section>

  {#if vol && scene.wl}
    <!-- window / level on the histogram -->
    <section title="Okno/poziom widoków 2D — przeciągnij pasmo lub jego krawędzie (albo PPM w widoku)">
      {#if scene.meta?.stats?.histogram}
        <WindowHistogram
          histogram={scene.meta.stats.histogram}
          min={scene.meta.stats.min}
          max={scene.meta.stats.max}
          wl={scene.wl}
          onchange={setWL}
        />
      {/if}
      <div class="wlvals"><span>O <b>{num(scene.wl.center, 0)}</b></span><span>S <b>{num(scene.wl.width, 0)}</b></span></div>
      <div class="chips">
        {#each wlPresets as p (p.name)}
          <button class="chip" class:active={isWL(p.wl)} title="{p.wl.center} / {p.wl.width}" onclick={() => setWL({ ...p.wl })}>
            {p.name}
          </button>
        {/each}
      </div>
    </section>

    <!-- 3-D presets as colour swatches -->
    <section>
      <div class="tiles">
        {#each tfPresetsFor(vol) as id (id)}
          <button class="tile" class:active={scene.tf === id} onclick={() => setTf(id)} title="Rendering 3D: {TF_SHORT[id]}">
            <span class="sw" style:background-image={swatch(id)}></span>
            <span class="tl">{TF_SHORT[id]}</span>
          </button>
        {/each}
      </div>
    </section>

    {#if hasOverlay}
      <section class="ovs" title="Wygląd segmentu w widokach 2D">
        <div class="ovh"><i style:background="var(--port-segment)"></i>Segment w 2D<b>{Math.round(scene.overlayAlpha * 100)}%</b></div>
        <div class="ovr">
          <button
            class="ico ovb"
            class:active={scene.overlayOutline}
            title="Kontur segmentu: {scene.overlayOutline ? 'włączony' : 'wyłączony'}"
            onclick={() => setOverlayStyle(scene.overlayAlpha, !scene.overlayOutline)}
          >
            <svg width="22" height="18" viewBox="0 0 22 18"><ellipse cx="11" cy="9" rx="8" ry="6" fill="none" stroke="currentColor" stroke-width="2" /></svg>
          </button>
          <input
            type="range"
            min="0"
            max="0.9"
            step="0.05"
            title="Krycie wypełnienia"
            value={scene.overlayAlpha}
            oninput={(e) => setOverlayStyle(Number(e.currentTarget.value), scene.overlayOutline)}
          />
        </div>
      </section>
    {/if}

    {#if hasMesh}
      <section class="ovs" title="Krycie mesha w widoku 3D (w 2D: kontur przekroju)">
        <div class="ovh"><i style:background="var(--port-mesh)"></i>Mesh w 3D<b>{Math.round(scene.meshOpacity * 100)}%</b></div>
        <div class="ovr">
          <span class="ico ovb mico"><Icon name="mesh" size={16} /></span>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.05"
            title="Krycie powierzchni"
            value={scene.meshOpacity}
            oninput={(e) => setMeshOpacity(Number(e.currentTarget.value))}
          />
        </div>
      </section>
    {/if}

    {#if results.length}
      <section class="res" title="Wyniki pomiarów — kliknij, aby zobaczyć pełną tabelę i zapisać CSV">
        {#each results as r (r.id)}
          <button class="rcard" onclick={() => openTable(r.id, r.port)}>
            <span class="rh"><Icon name="table" size={12} />{r.label}<small>{r.v.rows.length}</small></span>
            {#if r.v.chart}
              <TableChart table={r.v} height={44} />
            {:else}
              {#each r.v.rows.slice(0, 4) as row, n (n)}
                <span class="kv"><span>{row.name}</span><b>{row.value === null ? "" : `${num(Number(row.value), 1)} ${row.unit ?? ""}`}</b></span>
              {/each}
            {/if}
          </button>
        {/each}
      </section>
    {/if}

    {#if scene.cursor}
      {@const c = scene.cursor}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
      <section
        class="cur"
        title="Kursor (LPS, mm) — klik: kopiuj · ⌘/Ctrl+klik: do przypiętej notatki"
        onclick={(e) => copyValue(`L ${num(c[0], 1)} · P ${num(c[1], 1)} · S ${num(c[2], 1)} mm`, e)}
      >
        <span><i class="x">L</i>{num(c[0], 1)}</span>
        <span><i class="y">P</i>{num(c[1], 1)}</span>
        <span><i class="z">S</i>{num(c[2], 1)}</span>
      </section>
    {/if}
  {/if}
</div>

<style>
  .panel {
    width: 270px;
    flex-shrink: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 12px;
    background: var(--bg-panel-2);
    border-left: 1px solid var(--line-1);
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .rcard {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 7px;
    text-align: left;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-left: 2px solid var(--port-tabela);
    border-radius: var(--radius-sm);
    cursor: zoom-in;
  }
  .rcard:hover {
    border-color: var(--line-3);
    border-left-color: var(--port-tabela);
  }
  .rh {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--port-tabela);
  }
  .rh small {
    margin-left: auto;
    color: var(--text-dim-4);
  }
  .kv {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 0.64rem;
    color: var(--text-dim-1);
  }
  .kv b {
    color: var(--text);
  }
  .lh {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
  }
  .layers {
    gap: 3px;
  }
  .lrow {
    height: 33px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px 0 2px;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-left: 3px solid var(--k);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .lrow:hover {
    border-color: var(--line-3);
    border-left-color: var(--k);
  }
  /* the layer the tools edit: only a ring on its dot — visibility is the eye's job */
  .lrow.off .lname {
    opacity: 0.45;
  }
  .lrow.dragging {
    position: relative;
    z-index: 5;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
  }
  .grip {
    padding: 0 3px;
    font-size: 0.6rem;
    letter-spacing: -2px;
    color: var(--text-dim-4);
    cursor: grab;
    touch-action: none;
  }
  .kind {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--k);
    flex-shrink: 0;
  }
  .pick {
    order: 5;
    width: 18px;
    height: 18px;
    padding: 0;
    border: 1px solid var(--line-3);
    border-radius: 50%;
    background: none;
    cursor: pointer;
  }
  .pick::-webkit-color-swatch-wrapper {
    padding: 0;
  }
  .pick::-webkit-color-swatch {
    border: none;
    border-radius: 50%;
  }
  .kind.tools {
    box-shadow: 0 0 0 2px var(--bg-deep), 0 0 0 3.5px var(--accent);
  }
  .lname {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    line-height: 1.15;
  }
  .lname b {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .lname small {
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  .lb {
    display: flex;
    padding: 3px;
    background: none;
    border: none;
    color: var(--text-dim-4);
    cursor: pointer;
  }
  .lb:hover,
  .lb.on {
    color: var(--text);
  }
  .lempty {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px;
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
    border: 1px dashed var(--line-2);
    border-radius: var(--radius-sm);
  }
  .icons {
    display: flex;
    gap: 6px;
  }
  .ico {
    flex: 1;
    display: flex;
    justify-content: center;
    padding: 5px 0;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .ico rect {
    fill: rgba(255, 255, 255, 0.18);
  }
  .ico rect.d3 {
    fill: rgba(91, 155, 213, 0.55);
  }
  .ico.active {
    border-color: var(--accent-a40);
    background: var(--accent-a10);
  }
  .ico.active rect {
    fill: var(--accent-a70);
  }
  .ico.active rect.d3 {
    fill: var(--accent);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .chip {
    padding: 3px 8px;
    font-size: 0.62rem;
    font-weight: 600;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-left: 3px solid var(--c, var(--line-2));
    border-radius: 4px;
    color: var(--text-dim-2);
    cursor: pointer;
  }
  .icons.small .chip {
    flex: 1;
  }
  .chip:hover {
    color: var(--text);
  }
  .chip.active {
    color: var(--accent);
    border-color: var(--accent-a40);
    background: var(--accent-a10);
  }
  .wlvals {
    display: flex;
    justify-content: space-between;
    font-size: 0.62rem;
    color: var(--text-dim-3);
  }
  .wlvals b {
    color: var(--text);
    font-weight: 600;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 5px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .tile.active {
    border-color: var(--accent-a70);
    box-shadow: 0 0 0 1px var(--accent-a30);
  }
  .sw {
    height: 22px;
    border-radius: 3px;
    background-color: #000;
  }
  .tl {
    font-size: 0.6rem;
    color: var(--text-dim-2);
    text-align: center;
  }
  .tile.active .tl {
    color: var(--accent);
  }
  .ovs {
    gap: 5px;
  }
  .ovh {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
  }
  .ovh i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
  .ovh b {
    margin-left: auto;
    font-weight: 600;
    color: var(--text);
  }
  .ovr {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .ovb {
    flex: 0 0 auto;
    padding: 4px 8px;
    color: var(--text-dim-2);
  }
  .ovb.active {
    color: var(--port-segment);
  }
  .ovs input {
    flex: 1;
    accent-color: var(--port-segment);
  }
  .ovb.mico {
    display: flex;
    color: var(--port-mesh);
    cursor: default;
  }
  .ovs .mico ~ input {
    accent-color: var(--port-mesh);
  }
  .cur {
    cursor: copy;
    flex-direction: row;
    justify-content: space-between;
    font-size: 0.66rem;
    color: var(--text-dim-1);
    padding: 6px 8px;
    background: var(--bg-deep);
    border-radius: var(--radius-sm);
  }
  .cur i {
    font-style: normal;
    font-weight: 700;
    margin-right: 4px;
  }
  .x {
    color: #e05a5a;
  }
  .y {
    color: #6cbf6c;
  }
  .z {
    color: #5b9bd5;
  }
</style>
