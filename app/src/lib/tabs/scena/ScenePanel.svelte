<script lang="ts">
  // Scene sidebar — visual first: thumbnails, layout icons, the window drawn on the
  // histogram, colour swatches for 3-D presets. Explanations live in tooltips.
  import { libraryVolumes, thumbUrl, type VolumeEntry } from "#lib/core/library.svelte.ts";
  import { num } from "#lib/ui/format.ts";
  import { graph, setDisplay } from "#lib/graph/store.svelte.ts";
  import { autoWindow, buildTf, CT_WINDOWS, tfPresetsFor, type TfPresetId } from "#lib/viewport/presets.ts";
  import {
    scene,
    selectVolume,
    setLayout,
    setSingle,
    setTf,
    setWL,
    setOverlayStyle,
    type Layout,
    type ViewId,
  } from "#lib/viewport/scene.svelte.ts";
  import WindowHistogram from "./WindowHistogram.svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import { nodeType } from "#lib/graph/registry.svelte.ts";
  import TableChart from "#lib/graph/TableChart.svelte";
  import { openTable, tableOf } from "#lib/graph/tableView.svelte.ts";

  let {
    vol,
    displayLabel,
    hasOverlay = false,
  }: { vol: VolumeEntry | undefined; displayLabel: string; hasOverlay?: boolean } = $props();

  // results of every measurement node, at a glance (click → full table + CSV)
  const results = $derived(
    graph.doc.nodes.flatMap((n) => {
      const t = nodeType(n.type);
      const port = t?.outputs.find((o) => o.kind === "tabela");
      const v = port ? tableOf(n.id, port.id) : null;
      return t && port && v && v.rows.length ? [{ id: n.id, port: port.id, label: t.label, v }] : [];
    }),
  );

  let picker = $state(false);
  function pickVolume(id: string): void {
    picker = false;
    if (graph.doc.display) setDisplay(null); // a library volume replaces the node output
    selectVolume(id);
  }

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
  <!-- volume -->
  <section class="vol">
    <button class="vcard" onclick={() => (picker = !picker)} title="Zmień wyświetlany wolumen">
      {#if displayLabel}
        <span class="node-ico">◆</span>
        <span class="vname"><b>{displayLabel}</b><small>wynik grafu</small></span>
      {:else if vol}
        <img src={thumbUrl(vol.id)} alt="" />
        <span class="vname"><b>{vol.name}</b><small>{vol.modality || vol.source} · {vol.size.join("×")}</small></span>
      {:else}
        <span class="vname"><small>brak wolumenu</small></span>
      {/if}
      <span class="caret">▾</span>
    </button>
    {#if picker}
      <div class="vlist">
        {#each libraryVolumes() as v (v.id)}
          <button class="vrow" class:active={!displayLabel && v.id === vol?.id} onclick={() => pickVolume(v.id)}>
            <img src={thumbUrl(v.id)} alt="" loading="lazy" />
            <span class="vname"><b>{v.name}</b><small>{v.modality || v.source}</small></span>
          </button>
        {/each}
      </div>
    {/if}
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
        <button
          class="ico ovb"
          class:active={scene.overlayOutline}
          title="Kontur"
          onclick={() => setOverlayStyle(scene.overlayAlpha, !scene.overlayOutline)}
        >
          <svg width="22" height="18" viewBox="0 0 22 18"><ellipse cx="11" cy="9" rx="8" ry="6" fill="none" stroke="currentColor" stroke-width="2" /></svg>
        </button>
        <svg class="fillico" width="18" height="18" viewBox="0 0 18 18"><ellipse cx="9" cy="9" rx="7" ry="5.5" fill="var(--port-segment)" opacity={scene.overlayAlpha + 0.15} /></svg>
        <input
          type="range"
          min="0"
          max="0.9"
          step="0.05"
          value={scene.overlayAlpha}
          oninput={(e) => setOverlayStyle(Number(e.currentTarget.value), scene.overlayOutline)}
        />
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
      <section class="cur" title="Kursor (LPS, mm)">
        <span><i class="x">L</i>{num(scene.cursor[0], 1)}</span>
        <span><i class="y">P</i>{num(scene.cursor[1], 1)}</span>
        <span><i class="z">S</i>{num(scene.cursor[2], 1)}</span>
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
  .vol {
    position: relative;
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
  .vcard,
  .vrow {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px;
    text-align: left;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .vcard:hover,
  .vrow:hover {
    border-color: var(--line-3);
  }
  img {
    width: 40px;
    height: 40px;
    object-fit: contain;
    background: #000;
    border-radius: 4px;
    flex-shrink: 0;
  }
  .node-ico {
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.1rem;
    color: var(--accent);
    background: var(--accent-a10);
    border-radius: 4px;
  }
  .vname {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .vname b {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .vname small {
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  .caret {
    font-size: 0.6rem;
    color: var(--text-dim-3);
  }
  .vlist {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 30;
    max-height: 320px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
  }
  .vrow.active {
    border-color: var(--accent-a40);
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
    flex-direction: row;
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
  .cur {
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
