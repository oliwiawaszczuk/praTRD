<script lang="ts">
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import { VOLUME_KINDS, type MeshOut, type NodeRun, type VolumeOut } from "./evaluation.svelte.ts";
  import { HEADER_H, NODE_W, PORT_R, ROW_H, THUMB_H } from "./layout.ts";
  import { exportMesh, meshThumbUrl } from "#lib/core/meshes.svelte.ts";
  import { inTauri } from "#lib/core/tauri.ts";
  import { showError } from "#lib/ui/dialogs.svelte.ts";
  import { toast } from "#lib/ui/toast.svelte.ts";
  import NodeThumb from "./NodeThumb.svelte";
  import ParamField from "./ParamField.svelte";
  import CropSummary from "./CropSummary.svelte";
  import SegWidgets from "./SegWidgets.svelte";
  import MarkupWidgets from "./MarkupWidgets.svelte";
  import TableChart from "./TableChart.svelte";
  import { openTable } from "./tableView.svelte.ts";
  import { nodeDoc, requestDocSection } from "#lib/tabs/dokumentacja/appdocs.svelte.ts";
  import { goToTab } from "#lib/core/nav.svelte.ts";
  import type { TableValue } from "./tables.ts";
  import { num } from "#lib/ui/format.ts";
  import { DOMAIN_COLOR } from "./registry.svelte.ts";
  import { setParam } from "./store.svelte.ts";
  import { PORT_COLORS, type GNode, type NodeTypeSchema } from "./types.ts";

  let {
    node,
    type,
    run,
    quality,
    progress,
    selected,
    displayed,
    onheaderdown,
    onportdown,
    oneye,
  }: {
    node: GNode;
    type: NodeTypeSchema;
    run: NodeRun | null;
    quality: "preview" | "full" | null;
    progress: number | null;
    selected: boolean;
    displayed: boolean;
    onheaderdown: (e: PointerEvent) => void;
    onportdown: (e: PointerEvent, side: "in" | "out", socket: string) => void;
    oneye: () => void;
  } = $props();

  const rows = $derived(Math.max(type.inputs.length, type.outputs.length));
  const visibleParams = $derived(
    type.params.filter((p) => !p.showIf || node.params[p.showIf[0]] === p.showIf[1]),
  );
  const volOut = $derived.by(() => {
    const o = run?.outputs ? Object.values(run.outputs).find((v) => VOLUME_KINDS.includes(v.kind)) : undefined;
    return o as VolumeOut | undefined;
  });
  const hasVolOut = $derived(type.outputs.some((o) => VOLUME_KINDS.includes(o.kind)));
  const hasMeshOut = $derived(type.outputs.some((o) => o.kind === "mesh"));
  const meshOut = $derived.by(() => {
    const o = run?.outputs ? Object.values(run.outputs).find((v) => v.kind === "mesh") : undefined;
    return o as MeshOut | undefined;
  });
  let exporting = $state(false);
  async function onExport(): Promise<void> {
    if (!meshOut || exporting) return;
    exporting = true;
    try {
      const path = await exportMesh(meshOut.ref, meshOut.info.name ?? type.label);
      if (path) toast(`Zapisano ${path.split(/[\\/]/).pop()}`, { icon: "check" });
    } catch (e) {
      await showError("Eksport nie powiódł się", e);
    } finally {
      exporting = false;
    }
  }
  const kilo = (n: number) => (n >= 1e6 ? `${num(n / 1e6, 2)} mln` : n >= 1e4 ? `${num(n / 1e3, 0)} tys.` : n.toLocaleString("pl-PL"));
  const runState = $derived(run?.state ?? null);
  // first table output (pomiary nodes) — chart on the card, full table in the window
  const tabPort = $derived(type.outputs.find((o) => o.kind === "tabela") ?? null);
  const tab = $derived.by(() => {
    const o = tabPort ? run?.outputs?.[tabPort.id] : undefined;
    return o && o.kind === "tabela" && "value" in o ? (o.value as TableValue) : null;
  });
</script>

<div
  class="node"
  class:busy={runState === "computing"}
  class:selected
  class:displayed
  style:transform="translate({node.x}px, {node.y}px)"
  style:width="{NODE_W}px"
  style:--dom={DOMAIN_COLOR[type.domain] ?? "var(--accent)"}
  style:--hh="{HEADER_H}px"
  data-node={node.id}
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <header style:height="{HEADER_H}px" onpointerdown={onheaderdown}>
    <span class="dot {runState ?? 'idle'}" title={run?.error ?? runState ?? ""}></span>
    <span class="title">{type.label}</span>
    {#if run?.ms !== undefined && runState === "done"}<span class="ms">{run.ms} ms</span>{/if}
    {#if run?.cached && runState === "done"}<span class="ms">cache</span>{/if}
    {#if meshOut && inTauri()}
      <button
        class="eye"
        title="Eksport STL / OBJ / PLY"
        disabled={exporting}
        onpointerdown={(e) => e.stopPropagation()}
        onclick={onExport}
      >
        {#if exporting}<ProgressRing size={13} />{:else}<Icon name="export" size={13} />{/if}
      </button>
    {/if}
    {#if hasVolOut || hasMeshOut}
      <button
        class="eye"
        class:on={displayed}
        title={displayed ? "Wyświetlany w viewportach" : "Pokaż w viewportach"}
        onpointerdown={(e) => e.stopPropagation()}
        onclick={oneye}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
        </svg>
      </button>
    {/if}
    {#if tabPort && tab}
      <button
        class="eye"
        title="Pełna tabela i eksport CSV"
        onpointerdown={(e) => e.stopPropagation()}
        onclick={() => openTable(node.id, tabPort.id)}
      >
        <Icon name="table" size={13} />
      </button>
    {/if}
    <button
      class="info"
      title="{nodeDoc(type.id, type.description).replace(/[#*`>]/g, '')}

Kliknij: dokumentacja"
      onpointerdown={(e) => e.stopPropagation()}
      onclick={() => {
        requestDocSection({ kind: "node", typeId: type.id });
        goToTab("dokumentacja");
      }}
    >
      <Icon name="info" size={12} />
    </button>
  </header>

  {#if runState === "computing" && progress !== null}
    <div class="prog"><div class="bar" style:transform="scaleX({progress})"></div></div>
  {/if}

  <div class="ports" style:height="{rows * ROW_H}px">
    {#each type.inputs as p, i (p.id)}
      <div class="port in" style:top="{i * ROW_H}px" style:height="{ROW_H}px">
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <span
          class="sock"
          style:--c={PORT_COLORS[p.kind]}
          style:width="{PORT_R * 2}px"
          style:height="{PORT_R * 2}px"
          data-sock="in:{node.id}:{p.id}"
          onpointerdown={(e) => onportdown(e, "in", p.id)}
        ></span>
        <span class="plabel">{p.label}</span>
      </div>
    {/each}
    {#each type.outputs as p, i (p.id)}
      <div class="port out" style:top="{i * ROW_H}px" style:height="{ROW_H}px">
        <span class="plabel">{p.label}</span>
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <span
          class="sock"
          style:--c={PORT_COLORS[p.kind]}
          style:width="{PORT_R * 2}px"
          style:height="{PORT_R * 2}px"
          data-sock="out:{node.id}:{p.id}"
          onpointerdown={(e) => onportdown(e, "out", p.id)}
        ></span>
      </div>
    {/each}
  </div>

  {#if type.widget === "cropbox"}
    <CropSummary {node} />
  {:else if type.widget === "threshold" || type.widget === "seeds" || type.widget === "brush"}
    <SegWidgets {node} {type} />
  {:else if type.widget === "markups"}
    <MarkupWidgets {node} />
  {:else}
    {#each visibleParams as p (p.key)}
      <ParamField {p} value={node.params[p.key]} onchange={(v) => setParam(node.id, p.key, v)} />
    {/each}
  {/if}

  {#if run?.error && (runState === "error" || runState === "blocked")}
    <div class="error">{run.error}</div>
  {/if}

  {#if volOut && (volOut.kind === "segment" || volOut.kind === "segmentacja")}
    <div class="segstat">
      {#if volOut.kind === "segment"}
        <i style:background={volOut.info.color ?? "#7bc47f"}></i>
      {:else}
        {#each (volOut.info.labels ?? []).slice(0, 8) as l (l.id)}<i style:background={l.color} title={l.name}></i>{/each}
      {/if}
      <span class="ml">{num(volOut.info.ml ?? 0, 2)} ml</span>
      <span class="vx">{(volOut.info.voxels ?? 0).toLocaleString("pl-PL")} vox</span>
    </div>
  {/if}

  {#if meshOut}
    <div class="segstat" title="{meshOut.info.faces.toLocaleString('pl-PL')} trójkątów · {meshOut.info.verts.toLocaleString('pl-PL')} wierzchołków">
      <i style:background={meshOut.info.color ?? "var(--port-mesh)"}></i>
      {#if meshOut.info.closed}
        <span class="ml">{num(meshOut.info.ml, 2)} ml</span>
      {:else}
        <span class="open" title="Mesh nie jest zamknięty ({meshOut.info.boundary} otwartych krawędzi) — objętość nieokreślona"><Icon name="alert" size={11} /></span>
      {/if}
      <span class="vx">{num(meshOut.info.area / 100, 1)} cm²</span>
      <span class="vx tri"><Icon name="mesh" size={10} />{kilo(meshOut.info.faces)}</span>
    </div>
    <div class="thumbwrap" class:stale={runState === "stale" || runState === "computing"}>
      <div class="mthumb" style:height="{THUMB_H}px">
        {#key meshOut.ref}<img class="thumb" src={meshThumbUrl(meshOut.ref)} alt="" decoding="async" />{/key}
      </div>
      {#if quality === "preview"}<span class="q">podgląd</span>{/if}
      {#if runState === "stale" || runState === "computing"}
        <span class="thring"><ProgressRing size={22} value={runState === "computing" ? progress : null} /></span>
      {/if}
    </div>
  {:else if hasMeshOut && (runState === "computing" || runState === "stale")}
    <div class="skeleton"><ProgressRing size={30} value={progress} /></div>
  {/if}

  {#if tabPort && tab?.chart}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div
      class="tabwrap"
      class:stale={runState === "stale" || runState === "computing"}
      title="Kliknij: pełna tabela"
      onpointerdown={(e) => e.stopPropagation()}
      onclick={() => openTable(node.id, tabPort.id)}
    >
      <TableChart table={tab} height={56} />
      {#if quality === "preview"}<span class="q">podgląd</span>{/if}
    </div>
  {:else if tabPort && !tab && type.widget !== "markups" && (runState === "computing" || runState === "stale")}
    <div class="skeleton"><ProgressRing size={30} value={progress} /></div>
  {/if}

  {#if hasVolOut && volOut}
    <div class="thumbwrap" class:stale={runState === "stale" || runState === "computing"}>
      <NodeThumb
        volRef={volOut.ref}
        window={volOut.info?.window}
        colors={volOut.kind === "segment"
          ? { 1: volOut.info.color ?? "#7bc47f" }
          : volOut.kind === "segmentacja"
            ? Object.fromEntries((volOut.info.labels ?? []).map((l) => [l.id, l.color]))
            : undefined}
      />
      {#if quality === "preview"}<span class="q">podgląd</span>{/if}
      {#if runState === "stale" || runState === "computing"}
        <span class="thring"><ProgressRing size={22} value={runState === "computing" ? progress : null} /></span>
      {/if}
    </div>
  {:else if hasVolOut && (runState === "computing" || runState === "stale")}
    <div class="skeleton"><ProgressRing size={30} value={progress} /></div>
  {/if}
</div>

<style>
  .node {
    position: absolute;
    left: 0;
    top: 0;
    /* own stacking context: a socket's z-index must not escape above other nodes */
    z-index: 1;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
    padding-bottom: 4px;
    font-size: var(--fs-xs);
  }
  .node.selected {
    border-color: var(--accent-a70);
    box-shadow: 0 0 0 1px var(--accent-a40), 0 6px 18px rgba(0, 0, 0, 0.35);
    z-index: 2;
  }
  header {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 0 8px 0 10px;
    border-bottom: 1px solid var(--line-1);
    border-top: 3px solid var(--dom);
    border-radius: var(--radius-md) var(--radius-md) 0 0;
    background: var(--bg-panel-2);
    cursor: grab;
  }
  .title {
    flex: 1;
    min-width: 0;
    font-weight: 600;
    color: var(--text-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ms {
    color: var(--text-dim-4);
    font-size: 0.6rem;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--line-3);
    flex-shrink: 0;
  }
  .dot.done {
    background: var(--ok);
  }
  .dot.computing {
    background: var(--accent);
    animation: pulse 0.9s ease-in-out infinite;
  }
  .dot.stale {
    background: var(--accent-a40);
  }
  .dot.error,
  .dot.blocked {
    background: var(--danger);
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .eye {
    display: flex;
    padding: 2px;
    background: none;
    border: none;
    color: var(--text-dim-4);
    cursor: pointer;
  }
  .eye:hover {
    color: var(--text);
  }
  .eye.on {
    color: var(--accent);
  }
  .info {
    display: flex;
    padding: 0;
    color: var(--text-dim-4);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .info:hover {
    color: var(--accent);
  }
  /* overlay, so the port rows never shift while a node computes */
  .prog {
    position: absolute;
    left: 0;
    right: 0;
    top: calc(var(--hh) - 2px);
    height: 2px;
    background: var(--line-1);
    overflow: hidden;
  }
  .bar {
    height: 100%;
    background: var(--accent);
    transform-origin: left;
  }
  .ports {
    position: relative;
  }
  .port {
    position: absolute;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .port.in {
    left: 0;
    padding-left: 12px;
  }
  .port.out {
    right: 0;
    padding-right: 12px;
  }
  .sock {
    position: absolute;
    border-radius: 50%;
    background: var(--c);
    border: 2px solid var(--bg-panel);
    box-shadow: 0 0 0 1px var(--c);
    cursor: crosshair;
    z-index: 5;
  }
  /* socket centre exactly on the node edge — matches layout.ts inputPos/outputPos */
  .port.in .sock {
    left: -7px;
  }
  .port.out .sock {
    right: -7px;
  }
  .sock:hover {
    transform: scale(1.3);
  }
  .plabel {
    color: var(--text-dim-1);
  }
  .error {
    margin: 4px 10px;
    padding: 4px 6px;
    font-size: 0.62rem;
    color: var(--danger);
    background: var(--danger-a15);
    border-radius: 4px;
  }
  .thumbwrap {
    position: relative;
  }
  .tabwrap {
    position: relative;
    margin: 4px 10px 6px;
    padding: 6px;
    border-radius: 6px;
    background: rgba(240, 98, 146, 0.06);
    border: 1px solid rgba(240, 98, 146, 0.18);
    cursor: zoom-in;
  }
  .tabwrap:hover {
    border-color: rgba(240, 98, 146, 0.5);
  }
  .tabwrap.stale {
    opacity: 0.55;
  }
  .tabwrap .q {
    top: -7px;
    right: 6px;
    bottom: auto;
    padding: 0 3px;
    background: var(--bg-panel);
  }
  .segstat {
    display: flex;
    align-items: center;
    gap: 5px;
    margin: 2px 10px 0;
    font-size: 0.64rem;
  }
  .segstat i {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .segstat .ml {
    font-weight: 700;
    color: var(--text-strong);
  }
  .segstat .vx {
    margin-left: auto;
    color: var(--text-dim-4);
    font-size: 0.56rem;
  }
  .segstat .tri {
    display: flex;
    align-items: center;
    gap: 2px;
    margin-left: 6px;
  }
  .segstat .open {
    display: flex;
    color: var(--warn, #f2c94c);
  }
  .mthumb {
    margin: 4px 10px 8px;
    border-radius: 4px;
    background: radial-gradient(circle at 50% 45%, #1c2423, #050606 75%);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  .mthumb img {
    max-width: 100%;
    max-height: 100%;
    animation: fadein 0.25s ease;
  }
  @keyframes fadein {
    from {
      opacity: 0;
    }
  }
  .thring {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
  }
  .skeleton {
    height: 96px;
    margin: 4px 10px 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    background: linear-gradient(100deg, #111 30%, #1f1f1f 50%, #111 70%);
    background-size: 220% 100%;
    animation: shimmer 1.2s linear infinite;
  }
  @keyframes shimmer {
    to {
      background-position: -220% 0;
    }
  }
  /* computing: a golden light runs around the card */
  .node.busy::before {
    content: "";
    position: absolute;
    inset: -2px;
    z-index: -1;
    border-radius: calc(var(--radius-md) + 2px);
    padding: 2px;
    background: conic-gradient(from var(--a), transparent 0 70%, var(--accent) 85%, transparent 100%);
    /* keep only a 2 px ring — never paint over the card itself */
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor;
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask-composite: exclude;
    pointer-events: none;
    animation: orbit 1.4s linear infinite;
  }
  @property --a {
    syntax: "<angle>";
    inherits: false;
    initial-value: 0deg;
  }
  @keyframes orbit {
    to {
      --a: 360deg;
    }
  }
  .thumbwrap.stale :global(.thumb) {
    opacity: 0.4;
  }
  .q {
    position: absolute;
    right: 14px;
    bottom: 12px;
    font-size: 0.56rem;
    color: var(--text-dim-3);
  }
</style>
