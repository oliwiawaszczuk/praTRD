<script lang="ts">
  // Tablica — Miro-like whiteboard (ported from praSzczur): boards are global, a workspace
  // remembers the last open one. Undo history (100 steps), keyboard shortcuts while the tab
  // is visible, image paste / drop, viewport screenshots placed live (board.svelte.ts).
  import { onMount } from "svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import { showError } from "#lib/ui/dialogs.svelte.ts";
  import { toast } from "#lib/ui/toast.svelte.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import { getSetting } from "#lib/core/appSettings.svelte.ts";
  import { openShortcuts } from "#lib/ui/shortcuts.svelte.ts";
  import BoardCanvas from "./BoardCanvas.svelte";
  import BoardSidebar from "./BoardSidebar.svelte";
  import {
    boards,
    createBoard,
    deleteBoard,
    flushBoard,
    getBoard,
    loadBoards,
    registerBoardDrop,
    registerLiveBoard,
    renameBoard,
    savePng,
    scheduleSaveBoard,
    type BoardData,
    type BoardObject,
    type BoardTool,
    type BoardViewport,
  } from "./board.svelte.ts";

  let ready = $state(false);
  let activeId = $state("");
  let objects = $state.raw<BoardObject[]>([]);
  let viewport = $state.raw<BoardViewport>({ x: 0, y: 0, zoom: 1 });
  let selectedIds = $state<string[]>([]);
  let canvas = $state<BoardCanvas>();
  let loadKey = $state(0); // remounts the canvas (other board / undo)
  let root = $state<HTMLDivElement>();
  let clipboard: BoardObject[] = [];

  let tool = $state<BoardTool>("select");
  let draw = $state(wsGet("tablica_draw", { color: "#ffc951", width: 4 }));
  let shape = $state(
    wsGet("tablica_shape", {
      kind: "rect" as "rect" | "ellipse",
      fillColor: "#ffc951",
      fillTransparent: false,
      strokeColor: "#ffc951",
      strokeWidth: 2,
      strokeTransparent: true,
      cornerRadius: 4,
    }),
  );
  const zoomSensitivity = $derived(getSetting("canvasZoomSensitivity", 1));
  const panSensitivity = $derived(getSetting("canvasPanSensitivity", 1));

  // ── history (Cmd+Z / Cmd+Shift+Z) ──
  let history: BoardData[] = [];
  let hIndex = -1;
  let hTimer: ReturnType<typeof setTimeout> | null = null;
  const snapshot = (): BoardData => structuredClone({ objects: $state.snapshot(objects), viewport: $state.snapshot(viewport) }) as BoardData;

  const selected = $derived(objects.filter((o) => selectedIds.includes(o.id)));
  const sortedBoards = $derived([...boards()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
  const visible = () => !!root?.offsetParent; // the tab stays mounted while hidden

  onMount(() => {
    void (async () => {
      await loadBoards();
      let id = wsGet<string>("tablica_activeBoardId", "");
      if (!boards().some((b) => b.id === id)) id = boards()[0]?.id ?? (await createBoard("Tablica 1")).id;
      await openBoard(id);
      ready = true;
    })();
    registerBoardDrop((paths) => {
      for (const p of paths) void canvas?.addImageFromPath(p, activeId).catch((e) => showError("Nie udało się dodać obrazu", e));
    });
    return () => {
      canvas?.flushTextEdit();
      void flushBoard();
      registerLiveBoard(null, null);
      registerBoardDrop(null);
      if (hTimer) clearTimeout(hTimer);
    };
  });

  // screenshots from the viewports go straight onto the open board
  $effect(() => {
    const id = activeId;
    const c = canvas;
    if (!id || !c) return;
    registerLiveBoard(id, (url, w, h, caption) => c.placeImage(url, w, h, caption));
    return () => registerLiveBoard(null, null);
  });

  async function openBoard(id: string): Promise<void> {
    canvas?.flushTextEdit();
    await flushBoard();
    const data = await getBoard(id);
    objects = data.objects ?? [];
    viewport = data.viewport ?? { x: 0, y: 0, zoom: 1 };
    selectedIds = [];
    tool = "select";
    activeId = id;
    wsSet("tablica_activeBoardId", id);
    history = [structuredClone(data)];
    hIndex = 0;
    loadKey++;
  }

  function persist(o: BoardObject[], v: BoardViewport): void {
    objects = [...o]; // objects are edited in place by the canvas: a new array refreshes the sidebar
    viewport = v;
    scheduleSaveBoard(activeId, { objects: o, viewport: v });
  }
  function pushHistory(): void {
    if (hTimer) clearTimeout(hTimer);
    hTimer = setTimeout(() => {
      history = history.slice(0, hIndex + 1);
      history.push(snapshot());
      if (history.length > 100) history.shift();
      hIndex = history.length - 1;
    }, 400);
  }
  function applySnap(s: BoardData): void {
    objects = structuredClone(s.objects);
    viewport = structuredClone(s.viewport);
    selectedIds = [];
    loadKey++;
    scheduleSaveBoard(activeId, snapshot());
  }
  function undo(): void {
    canvas?.flushTextEdit();
    if (hTimer) clearTimeout(hTimer);
    hTimer = null;
    if (hIndex <= 0) return;
    applySnap(history[--hIndex]);
  }
  function redo(): void {
    canvas?.flushTextEdit();
    if (hTimer) clearTimeout(hTimer);
    hTimer = null;
    if (hIndex >= history.length - 1) return;
    applySnap(history[++hIndex]);
  }

  async function onCreate(name: string): Promise<void> {
    await openBoard((await createBoard(name)).id);
  }
  async function onDelete(id: string): Promise<void> {
    await deleteBoard(id);
    if (id === activeId) await openBoard(boards()[0]?.id ?? (await createBoard("Tablica 1")).id);
  }
  async function addFiles(files: File[]): Promise<void> {
    for (const f of files) await canvas?.addImageFromFile(f, activeId).catch((e) => showError("Nie udało się dodać obrazu", e));
  }
  async function exportPng(): Promise<void> {
    const blob = await canvas?.exportPNG();
    if (!blob) return toast("Tablica jest pusta", { icon: "info" });
    const name = `${boards().find((b) => b.id === activeId)?.name ?? "tablica"}.png`;
    try {
      const p = await savePng(blob, name);
      if (p) toast(`Zapisano ${p.split(/[\\/]/).pop()}`, { icon: "check" });
    } catch (e) {
      await showError("Nie udało się zapisać PNG", e);
    }
  }

  function onKey(e: KeyboardEvent): void {
    if (!ready || !visible()) return;
    const tag = (document.activeElement as HTMLElement | null)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();
    if (e.key === "Escape") {
      canvas?.clearSelection();
      tool = "select";
    } else if (e.key === "Delete" || e.key === "Backspace") canvas?.deleteSelected();
    else if (e.key === "ArrowUp") {
      e.preventDefault();
      canvas?.raiseSelected();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      canvas?.lowerSelected();
    } else if (mod) {
      if (k === "c") clipboard = canvas?.copySelected() ?? [];
      else if (k === "v" && clipboard.length) {
        // images from the system clipboard come through the paste event instead
        canvas?.pasteClipboard(clipboard);
      } else if (k === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (k === "y") {
        e.preventDefault();
        redo();
      }
    } else if (k === "t") canvas?.addTextAtCursorOrCenter();
    else if (k === "p") tool = tool === "draw" ? "select" : "draw";
    else if (k === "w") tool = "select";
    else if (k === "f") canvas?.fitToContent();
  }
  function onPaste(e: ClipboardEvent): void {
    if (!ready || !visible() || canvas?.isTextEditing()) return;
    const files = [...(e.clipboardData?.items ?? [])]
      .filter((i) => i.type.startsWith("image/"))
      .map((i) => i.getAsFile())
      .filter((f): f is File => !!f);
    if (files.length) {
      clipboard = []; // an image paste wins over the last copied board objects
      void addFiles(files);
    }
  }
</script>

<svelte:window onkeydown={onKey} onpaste={onPaste} />

<div class="tablica" bind:this={root}>
  {#if ready}
    <div class="area">
      {#key loadKey}
        <BoardCanvas
          bind:this={canvas}
          {objects}
          {viewport}
          {tool}
          drawColor={draw.color}
          drawStrokeWidth={draw.width}
          shapeKind={shape.kind}
          shapeFillColor={shape.fillColor}
          shapeFillTransparent={shape.fillTransparent}
          shapeStrokeColor={shape.strokeColor}
          shapeStrokeWidth={shape.strokeWidth}
          shapeStrokeTransparent={shape.strokeTransparent}
          shapeCornerRadius={shape.cornerRadius}
          {zoomSensitivity}
          {panSensitivity}
          onchange={persist}
          oncommit={pushHistory}
          onselect={(ids) => (selectedIds = ids)}
          ondropfiles={addFiles}
          ontextplaced={() => (tool = "select")}
        />
      {/key}
      {#if !objects.length}
        <div class="hint">
          <Icon name="camera" size={28} />
          <span>Zrzut z widoku Sceny trafia tutaj — albo przeciągnij / wklej obraz</span>
        </div>
      {/if}
      <div class="zoom">
        <button title="Dopasuj do zawartości (F)" onclick={() => canvas?.fitToContent()}>⛶</button>
        <span class="sep"></span>
        <button title="Pomniejsz" onclick={() => canvas?.zoomBy(-1)}>−</button>
        <span class="pct">{Math.round(viewport.zoom * 100)}%</span>
        <button title="Powiększ" onclick={() => canvas?.zoomBy(1)}>+</button>
      </div>
    </div>
    <div class="sidebar">
      <BoardSidebar
        boardList={sortedBoards}
        activeBoardId={activeId}
        {selected}
        {tool}
        {draw}
        {shape}
        onselectboard={openBoard}
        oncreateboard={onCreate}
        onrenameboard={(id, name) => renameBoard(id, name)}
        ondeleteboard={onDelete}
        onpropchange={(id, patch) => canvas?.updateObject(id, patch)}
        onaddimagefiles={addFiles}
        onsettool={(t) => (tool = t)}
        ondraw={(patch) => {
          draw = { ...draw, ...patch };
          wsSet("tablica_draw", draw);
        }}
        onshape={(patch) => {
          shape = { ...shape, ...patch };
          wsSet("tablica_shape", shape);
        }}
        onexportpng={exportPng}
        onshowshortcuts={() => openShortcuts("tablica")}
      />
    </div>
  {:else}
    <div class="loading">Wczytywanie tablicy…</div>
  {/if}
</div>

<style>
  .tablica {
    flex: 1;
    min-width: 0;
    height: 100%;
    display: flex;
    overflow: hidden;
  }
  .area {
    position: relative;
    flex: 1;
    min-width: 0;
  }
  .sidebar {
    width: 272px;
    flex-shrink: 0;
  }
  .hint {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    font-size: var(--fs-sm);
    color: var(--text-dim-4);
    pointer-events: none;
  }
  .zoom {
    position: absolute;
    right: 14px;
    bottom: 14px;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 3px;
    background: rgba(30, 30, 30, 0.85);
    border: 1px solid var(--line-3);
    border-radius: 9px;
  }
  .zoom button {
    width: 24px;
    height: 24px;
    font: inherit;
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-dim-1);
    background: none;
    border: 0;
    border-radius: 6px;
    cursor: pointer;
  }
  .zoom button:hover {
    color: var(--accent);
    background: var(--accent-a15);
  }
  .pct {
    min-width: 40px;
    text-align: center;
    font-size: 0.68rem;
    font-weight: 600;
    color: var(--text-dim-2);
  }
  .sep {
    width: 1px;
    height: 16px;
    margin: 0 2px;
    background: var(--line-3);
  }
  .loading {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-md);
    color: var(--text-dim-3);
  }
</style>
