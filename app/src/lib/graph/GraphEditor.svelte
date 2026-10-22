<script lang="ts">
  // Node-graph canvas (praSzczur interactions, Blender feel):
  //  wheel / two fingers → pan · ⌘/Ctrl + wheel / pinch → zoom at pointer · middle drag → pan
  //  drag empty → marquee (⇧ adds) · click node → select (⇧ toggles) · drag node → move group
  //  drag socket → connect (from a connected input: detach & re-route) · drop in empty → add menu
  //  right click / Space → add menu · Delete → delete (undo with ⌘Z) · F → fit · ⌘D duplicate
  //  ⌘C/⌘V copy/paste (DOM clipboard events — the native Edit menu triggers them)
  import { getSetting } from "#lib/core/appSettings.svelte.ts";
  import { confirmAction } from "#lib/ui/dialogs.svelte.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import AddMenu from "./AddMenu.svelte";
  import { bestRun, jobProgress, runs } from "./evaluation.svelte.ts";
  import GraphToolbar from "./GraphToolbar.svelte";
  import { edgePath, inputPos, NODE_W, nodeHeight, outputPos } from "./layout.ts";
  import NodeCard from "./NodeCard.svelte";
  import Palette from "./Palette.svelte";
  import { nodeType } from "./registry.svelte.ts";
  import {
    addNode,
    commit,
    connect,
    deleteNodes,
    graph,
    moveNodes,
    nodeById,
    pasteGraph,
    redo,
    removeEdge,
    select,
    serializeSelection,
    setDisplay,
    setView,
    toggleSelect,
    undo,
  } from "./store.svelte.ts";
  import { PORT_COLORS, type NodeTypeSchema, type PortKind } from "./types.ts";

  let { maximized = false, onmax }: { maximized?: boolean; onmax?: () => void } = $props();
  let host = $state<HTMLDivElement>();
  let W = $state(0);
  let H = $state(0);
  const view = $derived(graph.doc.view);

  const toWorld = (sx: number, sy: number): [number, number] => [(sx - view.x) / view.zoom, (sy - view.y) / view.zoom];
  function local(e: { clientX: number; clientY: number }): [number, number] {
    const r = host!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver(([e]) => {
      W = e.contentRect.width;
      H = e.contentRect.height;
    });
    ro.observe(host);
    return () => ro.disconnect();
  });

  // ── wheel: batch to one view update per frame ──────────────────────────────────
  let pendingView: typeof view | null = null;
  let wheelRaf = 0;
  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    const v = pendingView ?? { ...view };
    const zs = getSetting("canvasZoomSensitivity", 1);
    const ps = getSetting("canvasPanSensitivity", 1);
    if (e.ctrlKey || e.metaKey) {
      const [px, py] = local(e);
      const wx = (px - v.x) / v.zoom;
      const wy = (py - v.y) / v.zoom;
      const z = Math.min(2.5, Math.max(0.2, v.zoom * Math.exp(-e.deltaY * 0.01 * zs)));
      pendingView = { zoom: z, x: px - wx * z, y: py - wy * z };
    } else {
      pendingView = { ...v, x: v.x - e.deltaX * ps, y: v.y - e.deltaY * ps };
    }
    if (!wheelRaf)
      wheelRaf = requestAnimationFrame(() => {
        wheelRaf = 0;
        if (pendingView) setView(pendingView);
        pendingView = null;
      });
  }

  // ── pointer interactions ──────────────────────────────────────────────────────
  type ConnEnd = { node: string; socket: string; side: "in" | "out"; kind: PortKind };
  type Drag =
    | { kind: "pan"; sx: number; sy: number; vx: number; vy: number }
    | { kind: "nodes"; sx: number; sy: number; origin: Map<string, [number, number]>; moved: boolean; clicked: string; shift: boolean }
    | { kind: "marquee"; x0: number; y0: number; x1: number; y1: number; additive: boolean }
    | { kind: "conn"; from: ConnEnd; wx: number; wy: number };
  let drag = $state<Drag | null>(null);
  let mouse: [number, number] = [0, 0];
  let selectedEdge = $state<string | null>(null);
  let menu = $state<{ x: number; y: number; world: [number, number]; pending: ConnEnd | null } | null>(null);

  function onBgDown(e: PointerEvent): void {
    host!.focus();
    menu = null;
    const [sx, sy] = local(e);
    if (e.button === 1) {
      host!.setPointerCapture(e.pointerId);
      drag = { kind: "pan", sx, sy, vx: view.x, vy: view.y };
    } else if (e.button === 0) {
      host!.setPointerCapture(e.pointerId);
      drag = { kind: "marquee", x0: sx, y0: sy, x1: sx, y1: sy, additive: e.shiftKey };
    }
  }

  function onHeaderDown(e: PointerEvent, id: string): void {
    if (e.button !== 0) return;
    e.stopPropagation();
    host!.focus();
    menu = null;
    selectedEdge = null;
    if (e.shiftKey) toggleSelect(id);
    else if (!graph.selection.has(id)) select([id]);
    const origin = new Map<string, [number, number]>();
    for (const sid of graph.selection) {
      const n = nodeById(sid);
      if (n) origin.set(sid, [n.x, n.y]);
    }
    const [sx, sy] = local(e);
    host!.setPointerCapture(e.pointerId);
    drag = { kind: "nodes", sx, sy, origin, moved: false, clicked: id, shift: e.shiftKey };
  }

  function portKind(nodeId: string, side: "in" | "out", socket: string): PortKind | null {
    const n = nodeById(nodeId);
    const t = n && nodeType(n.type);
    const p = t && (side === "in" ? t.inputs : t.outputs).find((x) => x.id === socket);
    return p?.kind ?? null;
  }

  function onPortDown(e: PointerEvent, nodeId: string, side: "in" | "out", socket: string): void {
    if (e.button !== 0) return;
    e.stopPropagation();
    host!.focus();
    let from: ConnEnd | null = null;
    if (side === "in") {
      // grabbing a connected input detaches its edge and re-routes it (Blender)
      const existing = graph.doc.edges.find((x) => x.to === nodeId && x.toSocket === socket);
      if (existing) {
        removeEdge(existing.id);
        const k = portKind(existing.from, "out", existing.fromSocket);
        if (k) from = { node: existing.from, socket: existing.fromSocket, side: "out", kind: k };
      }
    }
    if (!from) {
      const k = portKind(nodeId, side, socket);
      if (!k) return;
      from = { node: nodeId, socket, side, kind: k };
    }
    const [wx, wy] = toWorld(...local(e));
    host!.setPointerCapture(e.pointerId);
    drag = { kind: "conn", from, wx, wy };
  }

  function onMove(e: PointerEvent): void {
    const [sx, sy] = local(e);
    mouse = [sx, sy];
    const d = drag;
    if (!d) return;
    if (d.kind === "pan") setView({ ...view, x: d.vx + sx - d.sx, y: d.vy + sy - d.sy });
    else if (d.kind === "nodes") {
      const dx = (sx - d.sx) / view.zoom;
      const dy = (sy - d.sy) / view.zoom;
      if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
      if (d.moved) moveNodes(d.origin.keys(), dx, dy, d.origin);
    } else if (d.kind === "marquee") {
      d.x1 = sx;
      d.y1 = sy;
    } else if (d.kind === "conn") {
      [d.wx, d.wy] = toWorld(sx, sy);
    }
  }

  function finishConn(d: Extract<Drag, { kind: "conn" }>, e: PointerEvent): void {
    const hit = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
    const sock = hit?.closest("[data-sock]")?.getAttribute("data-sock");
    const want: "in" | "out" = d.from.side === "out" ? "in" : "out";
    let target: { node: string; socket: string } | null = null;
    if (sock) {
      const [side, node, socket] = sock.split(":");
      if (side === want && portKind(node, want, socket) === d.from.kind) target = { node, socket };
    } else {
      // forgiving drop: nearest compatible socket within 22 px
      let best = 22;
      for (const n of graph.doc.nodes) {
        const t = nodeType(n.type);
        if (!t || n.id === d.from.node) continue;
        for (const p of want === "in" ? t.inputs : t.outputs) {
          if (p.kind !== d.from.kind) continue;
          const [px, py] = want === "in" ? inputPos(n, t, p.id) : outputPos(n, t, p.id);
          const dist = Math.hypot((px - d.wx) * view.zoom, (py - d.wy) * view.zoom);
          if (dist < best) {
            best = dist;
            target = { node: n.id, socket: p.id };
          }
        }
      }
    }
    if (target) {
      if (d.from.side === "out") connect(d.from.node, d.from.socket, target.node, target.socket);
      else connect(target.node, target.socket, d.from.node, d.from.socket);
    } else if (!hit?.closest(".node")) {
      // dropped on empty canvas → add menu filtered to compatible node types
      const [sx, sy] = local(e);
      menu = { x: sx, y: sy, world: [d.wx, d.wy], pending: d.from };
    }
  }

  function onUp(e: PointerEvent): void {
    const d = drag;
    drag = null;
    if (!d) return;
    if (d.kind === "nodes") {
      if (d.moved) commit();
      else if (!d.shift) select([d.clicked]);
    } else if (d.kind === "marquee") {
      const moved = Math.abs(d.x1 - d.x0) + Math.abs(d.y1 - d.y0) > 3;
      if (!moved) {
        if (!d.additive) select([]);
        selectedEdge = null;
        return;
      }
      const [ax, ay] = toWorld(Math.min(d.x0, d.x1), Math.min(d.y0, d.y1));
      const [bx, by] = toWorld(Math.max(d.x0, d.x1), Math.max(d.y0, d.y1));
      const hits = graph.doc.nodes.filter((n) => {
        const t = nodeType(n.type);
        const h = t ? nodeHeight(t) : 60;
        return n.x < bx && n.x + NODE_W > ax && n.y < by && n.y + h > ay;
      });
      select(hits.map((n) => n.id), d.additive);
    } else if (d.kind === "conn") finishConn(d, e);
  }

  function onContext(e: MouseEvent): void {
    e.preventDefault();
    if ((e.target as HTMLElement).closest(".node")) return;
    const [sx, sy] = local(e);
    menu = { x: sx, y: sy, world: toWorld(sx, sy), pending: null };
  }

  function pick(t: NodeTypeSchema): void {
    const m = menu;
    menu = null;
    if (!m) return;
    const n = addNode(t.id, m.world[0], m.world[1] - 15);
    if (n && m.pending) {
      const p = m.pending;
      const ports = p.side === "out" ? t.inputs : t.outputs;
      const s = ports.find((x) => x.kind === p.kind);
      if (s) {
        if (p.side === "out") connect(p.node, p.socket, n.id, s.id);
        else connect(n.id, s.id, p.node, p.socket);
      }
    }
    host?.focus();
  }

  // ── keyboard & clipboard ─────────────────────────────────────────────────────
  function fit(): void {
    const sel = graph.doc.nodes.filter((n) => graph.selection.has(n.id));
    const ns = sel.length ? sel : graph.doc.nodes;
    if (!ns.length || !W || !H) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of ns) {
      const t = nodeType(n.type);
      x0 = Math.min(x0, n.x);
      y0 = Math.min(y0, n.y);
      x1 = Math.max(x1, n.x + NODE_W);
      y1 = Math.max(y1, n.y + (t ? nodeHeight(t) : 60));
    }
    const pad = 40;
    const z = Math.min(1.5, Math.max(0.2, Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0))));
    setView({ zoom: z, x: (W - (x1 - x0) * z) / 2 - x0 * z, y: (H - (y1 - y0) * z) / 2 - y0 * z });
  }

  /** Delete the selection after a confirmation naming every node that goes (undo still works). */
  async function requestDelete(): Promise<void> {
    const ids = new Set(graph.selection);
    if (!ids.size) return;
    const names = graph.doc.nodes.filter((n) => ids.has(n.id)).map((n) => `• ${nodeType(n.type)?.label ?? n.type}`);
    const ok = await confirmAction(
      ids.size === 1 ? "Usunąć node?" : `Usunąć ${ids.size} node'y?`,
      `${names.join("\n")}\n\nPołączenia tych node'ów też znikną. Cofniesz to ⌘Z.`,
      { confirmText: "Usuń", danger: true },
    );
    if (ok) deleteNodes(ids);
    host?.focus();
  }

  const typing = (e: Event) => {
    const t = e.target as HTMLElement;
    return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT";
  };

  function onKey(e: KeyboardEvent): void {
    if (typing(e) || menu) return;
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      if (graph.selection.size) void requestDelete();
      else if (selectedEdge) {
        removeEdge(selectedEdge);
        selectedEdge = null;
      }
    } else if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    } else if (mod && e.key.toLowerCase() === "y") {
      e.preventDefault();
      redo();
    } else if (mod && e.key.toLowerCase() === "d") {
      e.preventDefault();
      const s = serializeSelection();
      if (s) {
        const first = graph.doc.nodes.find((n) => graph.selection.has(n.id))!;
        pasteGraph(s, [first.x + 30, first.y + 30]);
      }
    } else if (mod && e.key.toLowerCase() === "a") {
      e.preventDefault();
      select(graph.doc.nodes.map((n) => n.id));
    } else if (!mod && (e.key === "f" || e.key === "F")) fit();
    else if (e.key === " ") {
      e.preventDefault();
      menu = { x: mouse[0], y: mouse[1], world: toWorld(...mouse), pending: null };
    } else if (e.key === "Escape") {
      select([]);
      selectedEdge = null;
    }
  }

  const focused = () => !!host && host.contains(document.activeElement) && !typing({ target: document.activeElement } as Event);
  function onCopy(e: ClipboardEvent): void {
    if (!focused()) return;
    const s = serializeSelection();
    if (s) {
      e.clipboardData?.setData("text/plain", s);
      e.preventDefault();
    }
  }
  function onCut(e: ClipboardEvent): void {
    if (!focused()) return;
    onCopy(e);
    if (graph.selection.size) deleteNodes(new Set(graph.selection));
  }
  function onPaste(e: ClipboardEvent): void {
    if (!focused()) return;
    const text = e.clipboardData?.getData("text/plain");
    if (text && pasteGraph(text, toWorld(...mouse))) e.preventDefault();
  }

  // ── palette drop (pointer-based — HTML5 DnD is unreliable in WKWebView) ──────────
  function paletteDrop(typeId: string, clientX: number, clientY: number): void {
    const r = host!.getBoundingClientRect();
    if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) return;
    const [wx, wy] = toWorld(clientX - r.left, clientY - r.top);
    addNode(typeId, wx - NODE_W / 2, wy - 15);
    host!.focus();
  }

  let paletteOpen = $state(wsGet<boolean>("graph_paletteOpen", true));
  $effect(() => wsSet("graph_paletteOpen", paletteOpen));

  // ── edges ─────────────────────────────────────────────────────────────────────
  const edgePaths = $derived(
    graph.doc.edges.flatMap((e) => {
      const a = nodeById(e.from);
      const b = nodeById(e.to);
      const ta = a && nodeType(a.type);
      const tb = b && nodeType(b.type);
      if (!a || !b || !ta || !tb) return [];
      const kind = ta.outputs.find((p) => p.id === e.fromSocket)?.kind ?? "wolumen";
      return [{ id: e.id, d: edgePath(outputPos(a, ta, e.fromSocket), inputPos(b, tb, e.toSocket)), color: PORT_COLORS[kind] }];
    }),
  );

  const pendingPath = $derived.by(() => {
    const d = drag;
    if (d?.kind !== "conn") return null;
    const n = nodeById(d.from.node);
    const t = n && nodeType(n.type);
    if (!n || !t) return null;
    const p = d.from.side === "out" ? outputPos(n, t, d.from.socket) : inputPos(n, t, d.from.socket);
    const m: [number, number] = [d.wx, d.wy];
    return { d: d.from.side === "out" ? edgePath(p, m) : edgePath(m, p), color: PORT_COLORS[d.from.kind] };
  });

  const marquee = $derived(drag?.kind === "marquee" ? drag : null);
</script>

<svelte:window oncopy={onCopy} oncut={onCut} onpaste={onPaste} />

<div class="editor">
  <Palette bind:open={paletteOpen} ondrop={paletteDrop} />
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_static_element_interactions -->
  <div
    class="canvas"
    bind:this={host}
    tabindex="0"
    style:background-size="{22 * view.zoom}px {22 * view.zoom}px"
    style:background-position="{view.x}px {view.y}px"
    onpointerdown={onBgDown}
    onpointermove={onMove}
    onpointerup={onUp}
    onpointercancel={onUp}
    onwheel={onWheel}
    oncontextmenu={onContext}
    onkeydown={onKey}
  >
    <div class="world" style:transform="translate({view.x}px, {view.y}px) scale({view.zoom})">
      <svg class="edges" width="1" height="1">
        {#each edgePaths as e (e.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
          <g
            class="edge"
            class:sel={selectedEdge === e.id}
            onpointerdown={(ev) => {
              ev.stopPropagation();
              host?.focus();
              selectedEdge = e.id;
              select([]);
            }}
            ondblclick={() => removeEdge(e.id)}
          >
            <path class="hit" d={e.d} />
            <path class="line" d={e.d} stroke={e.color} />
          </g>
        {/each}
        {#if pendingPath}<path class="line pending" d={pendingPath.d} stroke={pendingPath.color} />{/if}
      </svg>
      {#each graph.doc.nodes as n (n.id)}
        {@const t = nodeType(n.type)}
        {#if t}
          {@const r = bestRun(n.id)}
          <NodeCard
            node={n}
            type={t}
            run={r}
            quality={r?.quality ?? null}
            progress={r?.state === "computing" ? jobProgress(r.quality) : null}
            selected={graph.selection.has(n.id)}
            displayed={graph.doc.display === n.id}
            onheaderdown={(e) => onHeaderDown(e, n.id)}
            onportdown={(e, side, s) => onPortDown(e, n.id, side, s)}
            oneye={() => setDisplay(graph.doc.display === n.id ? null : n.id)}
          />
        {/if}
      {/each}
    </div>

    {#if marquee}
      <div
        class="marquee"
        style:left="{Math.min(marquee.x0, marquee.x1)}px"
        style:top="{Math.min(marquee.y0, marquee.y1)}px"
        style:width="{Math.abs(marquee.x1 - marquee.x0)}px"
        style:height="{Math.abs(marquee.y1 - marquee.y0)}px"
      ></div>
    {/if}

    {#if !graph.doc.nodes.length}
      <div class="hint">Prawy klik albo spacja — dodaj node · przeciągnij z listy po lewej</div>
    {/if}

    {#if menu}
      <AddMenu
        x={menu.x}
        y={menu.y}
        bounds={{ w: W, h: H }}
        accept={menu.pending ? { side: menu.pending.side === "out" ? "in" : "out", kind: menu.pending.kind } : null}
        onpick={pick}
        onclose={() => {
          menu = null;
          host?.focus();
        }}
      />
    {/if}

    <GraphToolbar running={runs.previewJob} onfit={fit} {maximized} {onmax} />
  </div>
</div>

<style>
  .editor {
    width: 100%;
    height: 100%;
    display: flex;
    min-height: 0;
  }
  .canvas {
    position: relative;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    outline: none;
    background-color: var(--bg-deep);
    background-image: radial-gradient(var(--line-2) 1px, transparent 1px);
    touch-action: none;
    -webkit-user-select: none;
    user-select: none;
  }
  .world {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
    will-change: transform;
  }
  .edges {
    position: absolute;
    left: 0;
    top: 0;
    overflow: visible;
    pointer-events: none;
  }
  .edge {
    pointer-events: auto;
    cursor: pointer;
  }
  .hit {
    fill: none;
    stroke: transparent;
    stroke-width: 12;
  }
  .line {
    fill: none;
    stroke-width: 2;
    opacity: 0.85;
  }
  .edge.sel .line {
    stroke-width: 3.5;
    opacity: 1;
    filter: drop-shadow(0 0 3px rgba(255, 255, 255, 0.5));
  }
  .pending {
    stroke-dasharray: 6 4;
  }
  .marquee {
    position: absolute;
    border: 1px solid var(--accent-a70);
    background: var(--accent-a10);
    pointer-events: none;
  }
  .hint {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-xs);
    color: var(--text-dim-4);
    pointer-events: none;
  }
</style>
