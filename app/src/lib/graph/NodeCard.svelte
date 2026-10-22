<script lang="ts">
  import Icon from "#lib/ui/Icon.svelte";
  import ProgressRing from "#lib/ui/ProgressRing.svelte";
  import type { NodeRun, VolumeOut } from "./evaluation.svelte.ts";
  import { HEADER_H, NODE_W, PORT_R, ROW_H } from "./layout.ts";
  import NodeThumb from "./NodeThumb.svelte";
  import ParamField from "./ParamField.svelte";
  import CropSummary from "./CropSummary.svelte";
  import SegWidgets from "./SegWidgets.svelte";
  import MarkupWidgets from "./MarkupWidgets.svelte";
  import TableChart from "./TableChart.svelte";
  import { openTable } from "./tableView.svelte.ts";
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
    const o = run?.outputs ? Object.values(run.outputs).find((v) => ["wolumen", "segment", "segmentacja"].includes(v.kind)) : undefined;
    return o as VolumeOut | undefined;
  });
  const hasVolOut = $derived(type.outputs.some((o) => o.kind === "wolumen" || o.kind === "segment" || o.kind === "segmentacja"));
  const state = $derived(run?.state ?? null);
  // first table output (pomiary nodes) — chart on the card, full table in the window
  const tabPort = $derived(type.outputs.find((o) => o.kind === "tabela") ?? null);
  const tab = $derived.by(() => {
    const o = tabPort ? run?.outputs?.[tabPort.id] : undefined;
    return o && o.kind === "tabela" && "value" in o ? (o.value as TableValue) : null;
  });
</script>

<div
  class="node"
  class:busy={state === "computing"}
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
    <span class="dot {state ?? 'idle'}" title={run?.error ?? state ?? ""}></span>
    <span class="title">{type.label}</span>
    {#if run?.ms !== undefined && state === "done"}<span class="ms">{run.ms} ms</span>{/if}
    {#if run?.cached && state === "done"}<span class="ms">cache</span>{/if}
    {#if hasVolOut}
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
    <span class="info" title={type.description}><Icon name="info" size={12} /></span>
  </header>

  {#if state === "computing" && progress !== null}
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

  {#if run?.error && (state === "error" || state === "blocked")}
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

  {#if tabPort && tab?.chart}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div
      class="tabwrap"
      class:stale={state === "stale" || state === "computing"}
      title="Kliknij: pełna tabela"
      onpointerdown={(e) => e.stopPropagation()}
      onclick={() => openTable(node.id, tabPort.id)}
    >
      <TableChart table={tab} height={56} />
      {#if quality === "preview"}<span class="q">podgląd</span>{/if}
    </div>
  {:else if tabPort && !tab && type.widget !== "markups" && (state === "computing" || state === "stale")}
    <div class="skeleton"><ProgressRing size={30} value={progress} /></div>
  {/if}

  {#if hasVolOut && volOut}
    <div class="thumbwrap" class:stale={state === "stale" || state === "computing"}>
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
      {#if state === "stale" || state === "computing"}
        <span class="thring"><ProgressRing size={22} value={state === "computing" ? progress : null} /></span>
      {/if}
    </div>
  {:else if hasVolOut && (state === "computing" || state === "stale")}
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
    color: var(--text-dim-4);
    cursor: help;
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
