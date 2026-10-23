<script lang="ts">
  // Card editors of segmentation nodes (instead of generic params):
  //   threshold → input histogram with a draggable [od, do] band (views preview it live)
  //   seeds     → toggle "click seeds in a 2-D view", count, clear
  //   brush     → brush / eraser / scissors in the views, radius, undo last stroke, clear
  import { volumeMeta, type VolumeMeta } from "#lib/core/library.svelte.ts";
  import { num } from "#lib/ui/format.ts";
  import ParamField from "./ParamField.svelte";
  import RangeHistogram from "./RangeHistogram.svelte";
  import { segTools, setBrushR, setCut, setTool } from "./segTools.svelte.ts";
  import type { CutDepth, CutOp, CutShape } from "#lib/viewport/cuts.ts";
  import { commit, graph, setDisplay, setParam } from "./store.svelte.ts";
  import type { GNode, NodeTypeSchema } from "./types.ts";
  import { upstreamVolume } from "./upstream.ts";

  let { node, type }: { node: GNode; type: NodeTypeSchema } = $props();
  const stop = (e: Event) => e.stopPropagation();

  // ── threshold ──
  const input = $derived(type.widget === "threshold" ? upstreamVolume(node.id, "in") : null);
  let meta = $state.raw<VolumeMeta | null>(null);
  $effect(() => {
    const ref = input?.ref;
    if (!ref) {
      meta = null;
      return;
    }
    const ctl = new AbortController();
    volumeMeta(ref, ctl.signal).then((m) => (meta = m)).catch(() => {});
    return () => ctl.abort();
  });

  // ── tools ──
  const CUT_SHAPES: { v: CutShape; t: string; d: string }[] = [
    { v: "lasso", t: "Lasso — dowolny obrys", d: "M7 15C3 11 5 4 12 4s9 5 6 9-7 4-10 2M7 15l-2 5" },
    { v: "rect", t: "Prostokąt", d: "M4 6h16v12H4z" },
    { v: "ellipse", t: "Elipsa", d: "M12 5c4.4 0 8 3.1 8 7s-3.6 7-8 7-8-3.1-8-7 3.6-7 8-7z" },
  ];
  const CUT_OPS: { v: CutOp; t: string }[] = [
    { v: "erase", t: "Usuń wnętrze" },
    { v: "add", t: "Wypełnij wnętrze" },
    { v: "keep", t: "Zostaw tylko wnętrze (usuń resztę)" },
  ];
  const CUT_DEPTHS: { v: CutDepth; t: string; d: string }[] = [
    { v: "all", t: "Przez całą głębokość (jak w 3D)", d: "M4 7l8-3 8 3M4 12l8-3 8 3M4 17l8-3 8 3" },
    { v: "slice", t: "Tylko bieżący przekrój", d: "M4 12l8-3 8 3-8 3z" },
  ];

  function activate(t: "seed" | "brush" | "erase" | "cut"): void {
    if (segTools.tool === t && segTools.nodeId === node.id) {
      setTool(null);
      return;
    }
    setTool(t, node.id);
    if (graph.doc.display !== node.id) setDisplay(node.id); // see what you edit
  }
  const active = (t: string) => segTools.tool === t && segTools.nodeId === node.id;
  const seeds = $derived((node.params.seeds as unknown[]) ?? []);
  const strokes = $derived((node.params.strokes as unknown[]) ?? []);
  function clear(key: "seeds" | "strokes"): void {
    node.params[key] = [];
    commit();
  }
  function undoStroke(): void {
    node.params.strokes = strokes.slice(0, -1);
    commit();
  }
  const otherParams = $derived(
    type.params.filter(
      (p) =>
        p.type !== "points" &&
        p.type !== "strokes" &&
        !(type.widget === "threshold" && (p.key === "lo" || p.key === "hi")) &&
        (!p.showIf || node.params[p.showIf[0]] === p.showIf[1]),
    ),
  );
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="w" onpointerdown={stop} onwheel={stop}>
  {#if type.widget === "threshold"}
    {#if meta}
      <RangeHistogram
        histogram={meta.stats.histogram}
        min={meta.stats.min}
        max={meta.stats.max}
        lo={Number(node.params.lo)}
        hi={Number(node.params.hi)}
        onchange={(lo, hi) => {
          setParam(node.id, "lo", lo);
          setParam(node.id, "hi", hi);
        }}
      />
      <div class="vals">
        <input class="n" type="number" step="any" value={Number(node.params.lo)} onchange={(e) => setParam(node.id, "lo", Number(e.currentTarget.value))} />
        <span class="dash">–</span>
        <input class="n" type="number" step="any" value={Number(node.params.hi)} onchange={(e) => setParam(node.id, "hi", Number(e.currentTarget.value))} />
      </div>
    {:else}
      <div class="hint">podłącz wolumen</div>
    {/if}
  {:else if type.widget === "seeds"}
    <div class="tools">
      <button class="tb" class:on={active("seed")} title="Klikaj ziarna w widoku 2D (Esc kończy)" onclick={() => activate("seed")}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor" /><path d="M12 2v5M12 17v5M2 12h5M17 12h5" /></svg>
        <b>{seeds.length}</b>
      </button>
      {#if seeds.length}<button class="tb sm" title="Usuń wszystkie ziarna" onclick={() => clear("seeds")}>✕</button>{/if}
    </div>
  {:else if type.widget === "brush"}
    <div class="tools">
      <button class="tb" class:on={active("brush")} title="Pędzel — dodaje (Esc kończy)" onclick={() => activate("brush")}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20c3 0 5-2 5-4.5S7 12 5 13s-1 7-1 7zM9 14l10-10 2 2-10 10" /></svg>
      </button>
      <button class="tb" class:on={active("erase")} title="Gumka — usuwa" onclick={() => activate("erase")}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 20h11M5 15l9-9 5 5-9 9H8z" /></svg>
      </button>
      <button class="tb" class:on={active("cut")} title="Nożyce — obrysuj obszar w widoku 2D albo 3D (Shift + przeciągnięcie w 3D obraca)" onclick={() => activate("cut")}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="2.6" /><circle cx="6" cy="18" r="2.6" /><path d="M8.2 7.6L20 18M8.2 16.4L20 6" /></svg>
      </button>
      <span class="cnt" title="Pociągnięcia">{strokes.length}</span>
      {#if strokes.length}
        <button class="tb sm" title="Cofnij ostatnie pociągnięcie" onclick={undoStroke}>↶</button>
        <button class="tb sm" title="Usuń wszystkie pociągnięcia" onclick={() => clear("strokes")}>✕</button>
      {/if}
    </div>
    {#if active("cut")}
      <!-- scissors: shape · what happens inside · depth (2-D views; the 3-D view always cuts through) -->
      <div class="opts">
        <div class="seg" role="group" aria-label="Kształt">
          {#each CUT_SHAPES as o (o.v)}
            <button class:on={segTools.cut.shape === o.v} title={o.t} onclick={() => setCut({ shape: o.v })}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d={o.d} /></svg>
            </button>
          {/each}
        </div>
        <div class="seg" role="group" aria-label="Operacja">
          {#each CUT_OPS as o (o.v)}
            <button class:on={segTools.cut.op === o.v} title={o.t} onclick={() => setCut({ op: o.v })}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                {#if o.v === "keep"}<rect x="3" y="3" width="18" height="18" stroke-dasharray="3 2.5" /><rect x="8" y="8" width="8" height="8" fill="currentColor" />{:else}<rect x="4" y="4" width="16" height="16" /><path d={o.v === "add" ? "M12 8v8M8 12h8" : "M8 12h8"} />{/if}
              </svg>
            </button>
          {/each}
        </div>
        <div class="seg" role="group" aria-label="Głębokość">
          {#each CUT_DEPTHS as o (o.v)}
            <button class:on={segTools.cut.depth === o.v} title={o.t} onclick={() => setCut({ depth: o.v })}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d={o.d} /></svg>
            </button>
          {/each}
        </div>
      </div>
    {:else}
      <div class="radius" title="Promień pędzla ([ i ] w widoku)">
        <span class="dot" style:width="{Math.min(22, 4 + segTools.brushR * 1.2)}px" style:height="{Math.min(22, 4 + segTools.brushR * 1.2)}px"></span>
        <input type="range" min="0.5" max="25" step="0.5" value={segTools.brushR} oninput={(e) => setBrushR(Number(e.currentTarget.value))} />
        <span class="mm">{num(segTools.brushR, 1)} mm</span>
      </div>
    {/if}
  {/if}
</div>
{#each otherParams as p (p.key)}
  <ParamField {p} value={node.params[p.key]} onchange={(v) => setParam(node.id, p.key, v)} />
{/each}

<style>
  .w {
    margin: 4px 10px 6px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .vals {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .n {
    flex: 1;
    min-width: 0;
    padding: 2px 5px;
    font-size: 0.64rem;
    text-align: center;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 4px;
    color: var(--text);
  }
  .n::-webkit-inner-spin-button {
    display: none;
  }
  .dash {
    color: var(--text-dim-3);
  }
  .hint {
    font-size: 0.6rem;
    color: var(--text-dim-4);
    text-align: center;
    padding: 8px;
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tb {
    display: flex;
    align-items: center;
    gap: 5px;
    height: 28px;
    padding: 0 9px;
    font-size: 0.66rem;
    color: var(--text-dim-1);
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 6px;
    cursor: pointer;
  }
  .tb.sm {
    padding: 0 7px;
    color: var(--text-dim-3);
  }
  .tb:hover {
    color: var(--text);
    border-color: var(--line-3);
  }
  .tb.on {
    color: #111;
    background: var(--accent);
    border-color: var(--accent);
    box-shadow: 0 0 10px var(--accent-a40);
  }
  .tb b {
    font-weight: 700;
  }
  .cnt {
    margin-left: auto;
    min-width: 20px;
    padding: 1px 6px;
    font-size: 0.6rem;
    text-align: center;
    color: var(--text-dim-2);
    background: var(--bg-deepest);
    border-radius: 8px;
  }
  .opts {
    display: flex;
    gap: 5px;
  }
  .seg {
    display: flex;
    flex: 1;
    background: var(--bg-deepest);
    border: 1px solid var(--line-1);
    border-radius: 6px;
    overflow: hidden;
  }
  .seg button {
    flex: 1;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    cursor: pointer;
  }
  .seg button:hover {
    color: var(--text);
  }
  .seg button.on {
    color: #111;
    background: var(--accent);
  }
  .radius {
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .radius .dot {
    border-radius: 50%;
    background: var(--port-segment);
    flex-shrink: 0;
  }
  .radius input {
    flex: 1;
    accent-color: var(--accent);
  }
  .mm {
    font-size: 0.6rem;
    color: var(--text-dim-2);
    min-width: 38px;
    text-align: right;
  }
</style>
