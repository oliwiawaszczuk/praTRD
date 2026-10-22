<script lang="ts">
  // Chart of a "tabela" value from its hint: bars (one per segment, in its colour, with the
  // value), histogram, or a line (intensity profile). Plain SVG — a few hundred points at most.
  import { num } from "#lib/ui/format.ts";
  import type { TableValue } from "./tables.ts";

  let { table, height = 64, large = false }: { table: TableValue; height?: number; large?: boolean } = $props();

  const W = 200; // viewBox width; the SVG scales to its box
  const hint = $derived(table.chart);
  const unitOf = (key: string) => table.columns.find((c) => c.key === key)?.unit ?? "";

  const bars = $derived.by(() => {
    if (hint?.type !== "bars") return [];
    const rows = table.rows.slice(0, large ? 50 : 5);
    const max = Math.max(1e-9, ...rows.map((r) => Number(r[hint.value]) || 0));
    return rows.map((r) => ({
      label: String(r[hint.label] ?? ""),
      value: Number(r[hint.value]) || 0,
      f: (Number(r[hint.value]) || 0) / max,
      color: (hint.color && (r[hint.color] as string)) || "var(--port-tabela)",
    }));
  });

  const series = $derived.by(() => {
    if (hint?.type !== "histogram" && hint?.type !== "line") return null;
    const xs = table.rows.map((r) => Number(r[hint.x]));
    const ys = table.rows.map((r) => (r[hint.y] === null ? NaN : Number(r[hint.y])));
    const fin = ys.filter((y) => Number.isFinite(y));
    if (!fin.length) return null;
    let lo = Math.min(...fin);
    let hi = Math.max(...fin);
    if (hint.type === "histogram") lo = 0;
    if (hi <= lo) hi = lo + 1;
    const x0 = xs[0];
    const x1 = xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1];
    const px = (x: number) => ((x - x0) / (x1 - x0)) * W;
    const py = (y: number) => height - 2 - ((y - lo) / (hi - lo)) * (height - 4);
    let d = "";
    if (hint.type === "histogram") {
      const bw = W / ys.length;
      ys.forEach((y, n) => {
        if (y > 0) d += `M${n * bw},${height}V${py(y)}h${Math.max(0.6, bw - 0.4)}V${height}z`;
      });
    } else {
      let pen = false;
      ys.forEach((y, n) => {
        if (!Number.isFinite(y)) return void (pen = false);
        d += `${pen ? "L" : "M"}${px(xs[n]).toFixed(1)},${py(y).toFixed(1)}`;
        pen = true;
      });
    }
    return { d, lo, hi, x0, x1, kind: hint.type, xUnit: unitOf(hint.x), yUnit: unitOf(hint.y) };
  });
</script>

{#if bars.length}
  <div class="bars" class:large>
    {#each bars as b, n (n)}
      <div class="bar" title="{b.label}: {num(b.value, 2)} {hint?.type === 'bars' ? unitOf(hint.value) : ''}">
        <i style:background={b.color}></i>
        <span class="nm">{b.label}</span>
        <span class="track"><span class="fill" style:width="{Math.max(2, b.f * 100)}%" style:background={b.color}></span></span>
        <b>{num(b.value, b.value < 10 ? 2 : 1)}</b>
      </div>
    {/each}
    {#if !large && table.rows.length > bars.length}<div class="more">+{table.rows.length - bars.length}</div>{/if}
  </div>
{:else if series}
  <div class="plot" class:large>
    <svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" style:height="{height}px">
      <path d={series.d} class={series.kind} vector-effect="non-scaling-stroke" />
    </svg>
    <div class="ax">
      <span>{num(series.x0, 0)}</span>
      <span class="mid">{series.kind === "histogram" ? `max ${num(series.hi, 0)}` : `${num(series.lo, 0)} – ${num(series.hi, 0)}`}</span>
      <span>{num(series.x1, 0)}{series.xUnit ? ` ${series.xUnit}` : ""}</span>
    </div>
  </div>
{/if}

<style>
  .bars {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .bar {
    display: grid;
    grid-template-columns: 8px minmax(0, 0.9fr) 1fr auto;
    align-items: center;
    gap: 5px;
    font-size: 0.6rem;
  }
  .large .bar {
    font-size: 0.72rem;
    gap: 8px;
  }
  .bar i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .nm {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--text-dim-1);
  }
  .track {
    height: 6px;
    background: var(--bg-deepest);
    border-radius: 3px;
    overflow: hidden;
  }
  .fill {
    display: block;
    height: 100%;
    border-radius: 3px;
    opacity: 0.85;
  }
  .bar b {
    color: var(--text);
    font-weight: 700;
    text-align: right;
    min-width: 34px;
  }
  .more {
    font-size: 0.56rem;
    color: var(--text-dim-4);
    text-align: right;
  }
  .plot svg {
    display: block;
    width: 100%;
    background: var(--bg-deepest);
    border-radius: 4px;
  }
  .histogram {
    fill: var(--port-tabela);
    opacity: 0.85;
  }
  .line {
    fill: none;
    stroke: var(--port-tabela);
    stroke-width: 1.5;
  }
  .ax {
    display: flex;
    justify-content: space-between;
    font-size: 0.56rem;
    color: var(--text-dim-3);
    margin-top: 2px;
  }
  .large .ax {
    font-size: 0.68rem;
  }
  .mid {
    color: var(--text-dim-2);
  }
</style>
