<script lang="ts">
  // Markups on a 2-D view: what lies on the shown slice is drawn solid with draggable
  // handles; a ruler / angle crossing the slice is drawn faint. With a markup tool active the
  // layer takes the left button: click (ruler: click-click or drag), angle: three clicks,
  // ROI: drag a rectangle. Wheel, right and middle button still reach the view.
  import { cancelDraft, draftBox, draftClick, draftHover, finishBox, markupDraft, setLive, shownItems } from "./markupDraft.svelte.ts";
  import { MARKUP_COLOR, measureText, roiBox, type Markup, type MarkupType } from "./markups.ts";
  import type { Vec3 } from "./geometry.ts";
  import type { SliceLayers, ViewProj } from "./layers.ts";

  let { proj, layers }: { proj: ViewProj; layers: SliceLayers } = $props();

  const MARKUP_TOOLS: MarkupType[] = ["point", "line", "angle", "roi"];
  const placing = $derived(
    layers.tool && MARKUP_TOOLS.includes(layers.tool as MarkupType) && layers.toolNode ? (layers.tool as MarkupType) : null,
  );
  const itemsOf = (nodeId: string) => layers.markups.find((g) => g.nodeId === nodeId)?.items ?? [];

  interface Shape {
    key: string;
    nodeId: string;
    m: Markup;
    draft: boolean;
    pts: { x: number; y: number; on: boolean; idx: number }[];
    rect: { x: number; y: number; w: number; h: number; corners: { x: number; y: number; cu: "lo" | "hi"; cv: "lo" | "hi" }[] } | null;
    label: { x: number; y: number; text: string } | null;
    focus: boolean;
  }

  const shapes = $derived.by<Shape[]>(() => {
    const out: Shape[] = [];
    const [au, av] = proj.axes;
    for (const g of layers.markups) {
      for (const { m, draft } of shownItems(g.nodeId, g.items)) {
        const focus = layers.focusMarkup === m.id || draft;
        if (m.type === "roi") {
          const { lo, hi } = roiBox(m);
          const d0 = proj.depth(lo);
          const d1 = proj.depth(hi);
          if (Math.min(d0, d1) > proj.tol || Math.max(d0, d1) < -proj.tol) continue;
          const a = proj.toScreen(lo);
          const b = proj.toScreen(hi);
          const x = Math.min(a[0], b[0]);
          const y = Math.min(a[1], b[1]);
          const w = Math.abs(b[0] - a[0]);
          const h = Math.abs(b[1] - a[1]);
          const corners = (["lo", "hi"] as const).flatMap((cu) =>
            (["lo", "hi"] as const).map((cv) => {
              const p: Vec3 = [...lo] as Vec3;
              p[au] = (cu === "lo" ? lo : hi)[au];
              p[av] = (cv === "lo" ? lo : hi)[av];
              const [sx, sy] = proj.toScreen(p);
              return { x: sx, y: sy, cu, cv };
            }),
          );
          out.push({
            key: `${g.nodeId}:${m.id}`, nodeId: g.nodeId, m, draft, pts: [], focus,
            rect: { x, y, w, h, corners },
            label: { x: x + w / 2, y: y - 7, text: measureText(m) },
          });
          continue;
        }
        const pts = m.p.map((p, idx) => {
          const [x, y] = proj.toScreen(p);
          return { x, y, on: Math.abs(proj.depth(p)) <= proj.tol, idx };
        });
        if (!pts.some((p) => p.on)) continue;
        const at = m.type === "angle" ? pts[1] : m.type === "line" ? { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 } : pts[0];
        const text = m.type === "point" ? m.name : measureText(m);
        out.push({
          key: `${g.nodeId}:${m.id}`, nodeId: g.nodeId, m, draft, pts, rect: null, focus,
          label: { x: at.x + 9, y: at.y - 9, text },
        });
      }
    }
    return out;
  });

  /** Arc at the vertex of an angle (screen space), radius 18 px. */
  function arcPath(s: Shape): string {
    const [a, v, b] = s.pts;
    const r = 18;
    const a1 = Math.atan2(a.y - v.y, a.x - v.x);
    const a2 = Math.atan2(b.y - v.y, b.x - v.x);
    let d = a2 - a1;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    const p1 = [v.x + r * Math.cos(a1), v.y + r * Math.sin(a1)];
    const p2 = [v.x + r * Math.cos(a1 + d), v.y + r * Math.sin(a1 + d)];
    return `M${p1[0]},${p1[1]} A${r},${r} 0 0 ${d > 0 ? 1 : 0} ${p2[0]},${p2[1]}`;
  }

  // ── dragging handles ──
  let svg = $state<SVGSVGElement>();
  const local = (e: PointerEvent): [number, number] => {
    const r = svg!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  let drag:
    | { nodeId: string; m: Markup; idx: number; corner: null }
    | { nodeId: string; m: Markup; idx: -1; corner: { fu: number; fv: number } }
    | null = null;

  function onHandleDown(e: PointerEvent, s: Shape, idx: number, corner?: { cu: "lo" | "hi"; cv: "lo" | "hi" }): void {
    if (e.button !== 0 || s.draft) return;
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const m = $state.snapshot(s.m) as Markup;
    if (corner) {
      const { lo, hi } = roiBox(m);
      const [au, av] = proj.axes;
      // the opposite corner stays put
      drag = { nodeId: s.nodeId, m, idx: -1, corner: { fu: (corner.cu === "lo" ? hi : lo)[au], fv: (corner.cv === "lo" ? hi : lo)[av] } };
    } else drag = { nodeId: s.nodeId, m, idx, corner: null };
  }
  function onHandleMove(e: PointerEvent): void {
    if (!drag) return;
    e.stopPropagation();
    const w = proj.worldAt(...local(e));
    const m = drag.m;
    if (drag.corner) {
      const { lo, hi } = roiBox(m);
      const [au, av] = proj.axes;
      lo[au] = Math.min(w[au], drag.corner.fu);
      hi[au] = Math.max(w[au], drag.corner.fu);
      lo[av] = Math.min(w[av], drag.corner.fv);
      hi[av] = Math.max(w[av], drag.corner.fv);
      m.p = [lo, hi];
    } else m.p[drag.idx] = w;
    setLive(drag.nodeId, { ...m, p: m.p.map((q) => [...q] as Vec3) });
  }
  function onHandleUp(e: PointerEvent): void {
    if (!drag) return;
    e.stopPropagation();
    const d = drag;
    drag = null;
    const items = itemsOf(d.nodeId).map((x) => (x.id === d.m.id ? d.m : x));
    layers.onMarkups?.(d.nodeId, items);
    setLive(d.nodeId, null);
  }

  // ── placing with a tool ──
  let press: { x: number; y: number; a: Vec3 } | null = null;
  function boxFrom(a: Vec3, b: Vec3): [Vec3, Vec3] {
    // depth along the normal = the smaller in-plane side, centred on the slice
    const [au, av, an] = proj.axes;
    const half = Math.max(1, Math.min(Math.abs(b[au] - a[au]), Math.abs(b[av] - a[av]))) / 2;
    const p: Vec3 = [...a] as Vec3;
    const q: Vec3 = [...b] as Vec3;
    p[an] = a[an] - half;
    q[an] = a[an] + half;
    return [p, q];
  }
  function onDown(e: PointerEvent): void {
    if (!placing || !layers.toolNode || e.button !== 0 || e.shiftKey) return;
    e.stopPropagation();
    svg!.setPointerCapture(e.pointerId);
    const [x, y] = local(e);
    const w = proj.worldAt(x, y);
    press = { x, y, a: w };
    const node = layers.toolNode;
    if (placing === "roi") {
      draftBox(node, ...boxFrom(w, w), itemsOf(node));
      return;
    }
    const done = draftClick(node, placing, w, itemsOf(node));
    if (done) layers.onMarkups?.(node, done);
  }
  function onMove(e: PointerEvent): void {
    if (!placing || !layers.toolNode) return;
    const [x, y] = local(e);
    const w = proj.worldAt(x, y);
    if (placing === "roi") {
      if (press) draftBox(layers.toolNode, ...boxFrom(press.a, w), itemsOf(layers.toolNode));
    } else draftHover(w);
  }
  function onUp(e: PointerEvent): void {
    if (!press || !layers.toolNode) return;
    const [x, y] = local(e);
    const moved = Math.hypot(x - press.x, y - press.y) > 5;
    const node = layers.toolNode;
    press = null;
    if (placing === "roi") {
      const done = moved ? finishBox(itemsOf(node)) : null;
      if (done) layers.onMarkups?.(node, done);
      else cancelDraft();
    } else if (placing === "line" && moved && markupDraft.draft?.m.type === "line") {
      // drag-to-measure: the release places the second end
      const done = draftClick(node, "line", proj.worldAt(x, y), itemsOf(node));
      if (done) layers.onMarkups?.(node, done);
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svg
  bind:this={svg}
  class="mk"
  class:placing={!!placing}
  onpointerdown={onDown}
  onpointermove={onMove}
  onpointerup={onUp}
  onpointercancel={() => (press = null)}
>
  {#each shapes as s (s.key)}
    <g class="shape" class:focus={s.focus} class:draft={s.draft} style:--c={MARKUP_COLOR}>
      {#if s.rect}
        <rect x={s.rect.x} y={s.rect.y} width={s.rect.w} height={s.rect.h} class="box" />
        {#each s.rect.corners as c (c.cu + c.cv)}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <circle
            cx={c.x}
            cy={c.y}
            r="4.5"
            class="h sq"
            onpointerdown={(e) => onHandleDown(e, s, -1, c)}
            onpointermove={onHandleMove}
            onpointerup={onHandleUp}
          />
        {/each}
      {:else}
        {#if s.pts.length > 1}
          <polyline points={s.pts.map((p) => `${p.x},${p.y}`).join(" ")} class="ln" class:faint={!s.pts.every((p) => p.on)} />
        {/if}
        {#if s.m.type === "angle" && s.pts.length === 3}
          <path d={arcPath(s)} class="arc" />
        {/if}
        {#each s.pts as p (p.idx)}
          {#if p.on}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <circle
              cx={p.x}
              cy={p.y}
              r={s.m.type === "point" ? 5.5 : 4.5}
              class="h"
              onpointerdown={(e) => onHandleDown(e, s, p.idx)}
              onpointermove={onHandleMove}
              onpointerup={onHandleUp}
            />
          {/if}
        {/each}
      {/if}
      {#if s.label && s.label.text}
        <text x={s.label.x} y={s.label.y} class="lbl" text-anchor={s.rect ? "middle" : "start"}>{s.label.text}</text>
      {/if}
    </g>
  {/each}
</svg>

<style>
  .mk {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    pointer-events: none;
  }
  .mk.placing {
    pointer-events: auto;
    cursor: crosshair;
  }
  .shape {
    color: var(--c);
  }
  .ln,
  .arc,
  .box {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.6;
  }
  .box {
    fill: currentColor;
    fill-opacity: 0.06;
  }
  .ln.faint {
    stroke-dasharray: 4 3;
    opacity: 0.55;
  }
  .arc {
    stroke-width: 1.2;
  }
  .h {
    fill: #111;
    stroke: currentColor;
    stroke-width: 2;
    pointer-events: auto;
    cursor: grab;
  }
  .h:hover {
    fill: currentColor;
  }
  .draft .h {
    pointer-events: none;
  }
  .focus {
    color: #fff;
  }
  .focus .ln,
  .focus .box {
    stroke-width: 2.2;
  }
  .lbl {
    font-size: 11px;
    font-weight: 600;
    fill: currentColor;
    filter: drop-shadow(0 0 1.5px #000) drop-shadow(0 0 1px #000);
    pointer-events: none;
  }
</style>
