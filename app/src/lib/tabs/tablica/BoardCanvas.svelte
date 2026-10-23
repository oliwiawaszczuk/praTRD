<script lang="ts">
  // Miro-like whiteboard canvas (Konva) — ported from praSzczur. Objects live in `objects`
  // (the board document); every change goes out through onchange (debounced save) and
  // oncommit (undo history). Konva is imported on first mount, not at app start.
  import { onMount } from "svelte";
  import type KonvaNS from "konva";
  import {
    assetFromPath,
    assetUrl,
    uploadAsset,
    type BoardObject,
    type BoardTool,
    type BoardViewport,
    type DrawObject,
    type ImageObject,
    type ShapeKind,
    type ShapeObject,
    type TextObject,
  } from "./board.svelte.ts";

  type Konva = typeof KonvaNS;
  type KNode = KonvaNS.Node;

  interface Props {
    objects: BoardObject[];
    viewport: BoardViewport;
    tool?: BoardTool;
    drawColor?: string;
    drawStrokeWidth?: number;
    shapeKind?: ShapeKind;
    shapeFillColor?: string;
    shapeFillTransparent?: boolean;
    shapeStrokeColor?: string;
    shapeStrokeWidth?: number;
    shapeStrokeTransparent?: boolean;
    shapeCornerRadius?: number;
    zoomSensitivity?: number;
    panSensitivity?: number;
    onchange?: (objects: BoardObject[], viewport: BoardViewport) => void;
    oncommit?: () => void;
    onselect?: (ids: string[]) => void;
    ondropfiles?: (files: File[]) => void;
    ontextplaced?: () => void;
  }

  let {
    objects,
    viewport,
    tool = "select",
    drawColor = "#ffc951",
    drawStrokeWidth = 4,
    shapeKind = "rect",
    shapeFillColor = "#ffc951",
    shapeFillTransparent = false,
    shapeStrokeColor = "#ffc951",
    shapeStrokeWidth = 2,
    shapeStrokeTransparent = true,
    shapeCornerRadius = 4,
    zoomSensitivity = 1,
    panSensitivity = 1,
    onchange,
    oncommit,
    onselect,
    ondropfiles,
    ontextplaced,
  }: Props = $props();

  // the document is mutated in place (Konva callbacks) — a local, non-reactive copy
  // svelte-ignore state_referenced_locally
  let objs: BoardObject[] = objects;
  // svelte-ignore state_referenced_locally
  let view: BoardViewport = { ...viewport };

  let container = $state<HTMLDivElement>();
  let K: Konva;
  let stage: KonvaNS.Stage;
  let objLayer: KonvaNS.Layer;
  let trLayer: KonvaNS.Layer;
  let transformer: KonvaNS.Transformer;
  let selectionRect: KonvaNS.Rect;
  let ready = false;

  const accent = () =>
    getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#ffc951";
  const FONT = "JetBrains Mono, monospace";

  const nodesById = new Map<string, KNode>();
  let selectedIds = new Set<string>();
  let spaceDown = false;
  let selecting = false;
  let selectStart = { x: 0, y: 0 };
  let editingTextarea: HTMLTextAreaElement | null = null;
  let drawing = false;
  let drawPoints: number[] = [];
  let tempLine: KonvaNS.Line | null = null;
  let shapeDrawing = false;
  let shapeStart = { x: 0, y: 0 };
  let tempShape: KonvaNS.Rect | KonvaNS.Ellipse | null = null;

  export function updateObject(id: string, patch: Partial<BoardObject>): void {
    const node = nodesById.get(id);
    const obj = objs.find((o) => o.id === id);
    if (!node || !obj) return;
    // rotation from the panel pivots around the centre, like the transformer's handle
    if (patch.rotation !== undefined && patch.rotation !== obj.rotation) {
      const r0 = (obj.rotation * Math.PI) / 180;
      const r1 = (patch.rotation * Math.PI) / 180;
      const hw = obj.width / 2;
      const hh = obj.height / 2;
      const cx = obj.x + hw * Math.cos(r0) - hh * Math.sin(r0);
      const cy = obj.y + hw * Math.sin(r0) + hh * Math.cos(r0);
      patch = { ...patch, x: cx - (hw * Math.cos(r1) - hh * Math.sin(r1)), y: cy - (hw * Math.sin(r1) + hh * Math.cos(r1)) };
    }
    Object.assign(obj, patch);
    applyObjectToNode(obj, node);
    objLayer.batchDraw();
    trLayer.batchDraw();
    emitChange(true);
  }

  export function deleteSelected(): void {
    if (!selectedIds.size) return;
    objs = objs.filter((o) => !selectedIds.has(o.id));
    for (const id of selectedIds) {
      nodesById.get(id)?.destroy();
      nodesById.delete(id);
    }
    clearSelection();
    objLayer.batchDraw();
    emitChange(true);
  }

  export function addText(at?: { x: number; y: number }, autoEdit = false, content = "Nowy tekst", fontSize = 20): TextObject {
    const c = at ?? stageCenterInWorld();
    const obj: TextObject = {
      id: crypto.randomUUID(),
      type: "text",
      x: at ? c.x : c.x - 80,
      y: at ? c.y : c.y - 20,
      width: 160,
      height: 40,
      rotation: 0,
      opacity: 1,
      zIndex: nextZ(),
      content,
      color: "#f0f0f0",
      fontSize,
      bold: false,
      align: "left",
      borderEnabled: false,
      borderColor: "#000000",
      borderWidth: 1.5,
    };
    objs = [...objs, obj];
    const node = createNode(obj);
    objLayer.batchDraw();
    selectOnly(obj.id);
    emitChange(true);
    if (autoEdit) startTextEdit(node as KonvaNS.Text, obj);
    return obj;
  }

  export function addTextAtCursorOrCenter(): void {
    const p = stage?.getPointerPosition();
    addText(p ? screenToWorld(p) : undefined, true);
  }

  /** An uploaded asset as an image object (fit to ≤ maxDim px), optionally captioned. */
  export function placeImage(url: string, w: number, h: number, caption = "", maxDim = 480): void {
    const s = Math.min(1, maxDim / Math.max(w, h, 1));
    const c = stageCenterInWorld();
    const iw = w * s;
    const ih = h * s;
    const obj: ImageObject = {
      id: crypto.randomUUID(),
      type: "image",
      x: c.x - iw / 2,
      y: c.y - ih / 2,
      width: iw,
      height: ih,
      rotation: 0,
      opacity: 1,
      zIndex: nextZ(),
      assetUrl: url,
      caption: caption || undefined,
    };
    objs = [...objs, obj];
    createNode(obj);
    const ids = [obj.id];
    if (caption) {
      const t = addText({ x: obj.x, y: obj.y + ih + 8 }, false, caption, 14);
      t.width = iw;
      t.color = "#bbbbbb";
      applyObjectToNode(t, nodesById.get(t.id)!);
      ids.push(t.id);
    }
    objLayer.batchDraw();
    selectMany(ids);
    emitChange(true);
  }

  const sizeOf = (src: string) =>
    new Promise<[number, number]>((res, rej) => {
      const img = new Image();
      img.onload = () => res([img.naturalWidth, img.naturalHeight]);
      img.onerror = rej;
      img.src = src;
    });

  export async function addImageFromFile(file: File, boardId: string): Promise<void> {
    const ext = (file.name.split(".").pop() || file.type.split("/")[1] || "png").toLowerCase();
    const url = await uploadAsset(boardId, file, ext === "jpeg" ? "jpg" : ext);
    const local = URL.createObjectURL(file);
    try {
      const [w, h] = await sizeOf(local);
      placeImage(url, w, h, "", 320);
    } finally {
      URL.revokeObjectURL(local);
    }
  }

  export async function addImageFromPath(path: string, boardId: string): Promise<void> {
    const url = await assetFromPath(boardId, path);
    const [w, h] = await sizeOf(assetUrl(url));
    placeImage(url, w, h, "", 320);
  }

  export function pasteClipboard(clip: BoardObject[]): void {
    if (!clip.length) return;
    const ids: string[] = [];
    for (const src of clip) {
      const copy = { ...structuredClone(src), id: crypto.randomUUID(), x: src.x + 24, y: src.y + 24, zIndex: nextZ() };
      objs = [...objs, copy];
      createNode(copy);
      ids.push(copy.id);
    }
    objLayer.batchDraw();
    selectMany(ids);
    emitChange(true);
  }

  export function copySelected(): BoardObject[] {
    return objs.filter((o) => selectedIds.has(o.id)).map((o) => structuredClone(o));
  }

  // z-order: jump over the nearest object that actually overlaps (↑ / ↓)
  function restack(up: boolean): void {
    if (!selectedIds.size) return;
    const sel = [...selectedIds].map((id) => nodesById.get(id)).filter(Boolean) as KNode[];
    sel.sort((a, b) => (up ? b.zIndex() - a.zIndex() : a.zIndex() - b.zIndex()));
    for (const n of sel) {
      const rect = n.getClientRect();
      const sib = objLayer.children ?? [];
      const idx = sib.indexOf(n as never);
      for (let i = up ? idx + 1 : idx - 1; up ? i < sib.length : i >= 0; i += up ? 1 : -1) {
        if (K.Util.haveIntersection(rect, sib[i].getClientRect())) {
          n.zIndex(i);
          break;
        }
      }
    }
    objLayer.children?.forEach((n, i) => {
      const o = objs.find((x) => x.id === n.id());
      if (o) o.zIndex = i;
    });
    objLayer.batchDraw();
    emitChange(true);
  }
  export const raiseSelected = () => restack(true);
  export const lowerSelected = () => restack(false);

  /** The whole board (not just the visible part) as a PNG blob, 2× pixel ratio. */
  export async function exportPNG(): Promise<Blob | null> {
    const rect = objLayer.getClientRect({ skipTransform: true });
    if (!rect.width || !rect.height) return null;
    const pad = 40;
    const prev = { s: stage.scaleX(), x: stage.x(), y: stage.y(), w: stage.width(), h: stage.height() };
    transformer.hide();
    selectionRect.hide();
    stage.scale({ x: 1, y: 1 });
    stage.position({ x: -rect.x + pad, y: -rect.y + pad });
    stage.size({ width: rect.width + pad * 2, height: rect.height + pad * 2 });
    const bg = new K.Rect({ x: rect.x - pad, y: rect.y - pad, width: rect.width + pad * 2, height: rect.height + pad * 2, fill: getComputedStyle(document.documentElement).getPropertyValue("--bg-deep").trim() || "#1a1a1a" });
    objLayer.add(bg);
    bg.moveToBottom();
    stage.draw();
    const blob = (await stage.toBlob({ pixelRatio: 2, mimeType: "image/png" })) as Blob;
    bg.destroy();
    stage.scale({ x: prev.s, y: prev.s });
    stage.position({ x: prev.x, y: prev.y });
    stage.size({ width: prev.w, height: prev.h });
    if (selectedIds.size) transformer.show();
    stage.batchDraw();
    return blob;
  }

  export function zoomBy(dir: 1 | -1): void {
    const w = container?.clientWidth ?? 800;
    const h = container?.clientHeight ?? 600;
    zoomAt({ x: w / 2, y: h / 2 }, Math.max(0.1, Math.min(4, view.zoom * (1 + dir * 0.15))));
  }

  function zoomAt(p: { x: number; y: number }, z: number): void {
    const to = { x: (p.x - view.x) / view.zoom, y: (p.y - view.y) / view.zoom };
    view = { zoom: z, x: p.x - to.x * z, y: p.y - to.y * z };
    applyStageTransform();
    emitChange();
  }

  export function fitToContent(): void {
    if (!objs.length) return;
    const rect = objLayer.getClientRect({ skipTransform: true });
    if (!rect.width || !rect.height) return;
    const w = container?.clientWidth ?? 800;
    const h = container?.clientHeight ?? 600;
    const z = Math.max(0.1, Math.min(2, Math.min((w - 120) / rect.width, (h - 120) / rect.height)));
    view = { zoom: z, x: w / 2 - (rect.x + rect.width / 2) * z, y: h / 2 - (rect.y + rect.height / 2) * z };
    applyStageTransform();
    emitChange();
  }

  const nextZ = () => objs.reduce((m, o) => Math.max(m, o.zIndex), -1) + 1;
  const screenToWorld = (p: { x: number; y: number }) => ({ x: (p.x - view.x) / view.zoom, y: (p.y - view.y) / view.zoom });
  function stageCenterInWorld(): { x: number; y: number } {
    return screenToWorld({ x: (container?.clientWidth ?? 800) / 2, y: (container?.clientHeight ?? 600) / 2 });
  }

  function emitChange(committed = false): void {
    onchange?.(objs, view);
    if (committed) oncommit?.();
  }

  function applyObjectToNode(obj: BoardObject, node: KNode): void {
    node.position({ x: obj.x, y: obj.y });
    node.rotation(obj.rotation);
    node.opacity(obj.opacity);
    node.size({ width: obj.width, height: obj.height });
    if (obj.type === "text") {
      const t = node as KonvaNS.Text;
      t.text(obj.content);
      t.fill(obj.color);
      t.fontSize(obj.fontSize);
      t.fontStyle(obj.bold ? "bold" : "normal");
      t.align(obj.align ?? "left");
      t.stroke(obj.borderEnabled ? (obj.borderColor ?? "#000000") : "");
      t.strokeWidth(obj.borderEnabled ? (obj.borderWidth ?? 1.5) : 0);
      t.fillAfterStrokeEnabled(true);
    } else if (obj.type === "draw") {
      const l = node as KonvaNS.Line;
      l.stroke(obj.color);
      l.strokeWidth(obj.strokeWidth);
      l.hitStrokeWidth(Math.max(14, obj.strokeWidth));
      l.points(obj.points);
    } else if (obj.type === "shape") {
      const sh = node as KonvaNS.Shape;
      sh.fill(obj.fillTransparent ? "" : obj.fillColor);
      sh.stroke(obj.strokeTransparent ? "" : obj.strokeColor);
      sh.strokeWidth(obj.strokeTransparent ? 0 : obj.strokeWidth);
      if (obj.shape === "ellipse") {
        // an ellipse is centred on (0,0): the offset keeps x/y = top-left like other types
        const e = node as KonvaNS.Ellipse;
        e.radiusX(obj.width / 2);
        e.radiusY(obj.height / 2);
        e.offsetX(-obj.width / 2);
        e.offsetY(-obj.height / 2);
      } else (node as KonvaNS.Rect).cornerRadius(obj.cornerRadius ?? 0);
    }
  }

  function createNode(obj: BoardObject): KNode {
    let node: KNode;
    const base = { id: obj.id, x: obj.x, y: obj.y, width: obj.width, height: obj.height, rotation: obj.rotation, opacity: obj.opacity, draggable: true };
    if (obj.type === "image") {
      const el = new Image();
      const img = new K.Image({ ...base, image: el });
      el.crossOrigin = "anonymous";
      el.onload = () => {
        img.image(el);
        objLayer.batchDraw();
      };
      el.src = assetUrl(obj.assetUrl);
      node = img;
    } else if (obj.type === "draw") {
      node = new K.Line({
        ...base,
        points: (obj as DrawObject).points,
        stroke: obj.color,
        strokeWidth: obj.strokeWidth,
        hitStrokeWidth: Math.max(14, obj.strokeWidth),
        lineCap: "round",
        lineJoin: "round",
        tension: 0.3,
      });
    } else if (obj.type === "shape") {
      const s = obj as ShapeObject;
      const paint = {
        fill: s.fillTransparent ? "" : s.fillColor,
        stroke: s.strokeTransparent ? "" : s.strokeColor,
        strokeWidth: s.strokeTransparent ? 0 : s.strokeWidth,
      };
      node =
        s.shape === "ellipse"
          ? new K.Ellipse({ ...base, ...paint, offsetX: -obj.width / 2, offsetY: -obj.height / 2, radiusX: obj.width / 2, radiusY: obj.height / 2 })
          : new K.Rect({ ...base, ...paint, cornerRadius: s.cornerRadius ?? 0 });
    } else {
      const t = obj as TextObject;
      node = new K.Text({
        ...base,
        text: t.content,
        fill: t.color,
        fontSize: t.fontSize,
        align: t.align ?? "left",
        fontStyle: t.bold ? "bold" : "normal",
        fontFamily: FONT,
        wrap: "word",
        stroke: t.borderEnabled ? t.borderColor : "",
        strokeWidth: t.borderEnabled ? t.borderWidth : 0,
        fillAfterStrokeEnabled: true,
      });
      node.on("dblclick dbltap", () => startTextEdit(node as KonvaNS.Text, t));
    }
    node.on("click tap", (e) => {
      e.cancelBubble = true;
      if ((e.evt as MouseEvent).shiftKey) toggleSelect(obj.id);
      else selectOnly(obj.id);
    });
    node.on("dragstart", () => {
      if (!selectedIds.has(obj.id)) selectOnly(obj.id);
    });
    node.on("dragmove", () => syncFromNode(obj.id, node));
    node.on("transform", () => syncFromNode(obj.id, node, true));
    node.on("dragend transformend", () => emitChange(true));
    objLayer.add(node as KonvaNS.Shape);
    nodesById.set(obj.id, node);
    return node;
  }

  function syncFromNode(id: string, node: KNode, transform = false): void {
    const obj = objs.find((o) => o.id === id);
    if (!obj) return;
    obj.x = node.x();
    obj.y = node.y();
    obj.rotation = node.rotation();
    if (transform) {
      const sx = node.scaleX();
      const sy = node.scaleY();
      if (obj.type === "draw") {
        obj.points = obj.points.map((v, i) => (i % 2 === 0 ? v * sx : v * sy));
        obj.width = Math.max(1, obj.width * sx);
        obj.height = Math.max(1, obj.height * sy);
      } else {
        // resize changes the box (text: wrap width), never the font size — like Miro
        obj.width = Math.max(20, node.width() * sx);
        obj.height = Math.max(obj.type === "text" ? 10 : 20, node.height() * sy);
      }
      node.scale({ x: 1, y: 1 });
      applyObjectToNode(obj, node);
    }
  }

  function startTextEdit(node: KonvaNS.Text, obj: TextObject): void {
    if (!container) return;
    node.hide();
    transformer.hide();
    objLayer.batchDraw();
    const abs = node.getAbsolutePosition();
    const z = view.zoom;
    const ta = document.createElement("textarea");
    ta.value = obj.content;
    Object.assign(ta.style, {
      position: "absolute",
      top: `${abs.y}px`,
      left: `${abs.x}px`,
      width: `${obj.width * z}px`,
      height: `${obj.height * z}px`,
      minWidth: "40px",
      minHeight: "24px",
      fontSize: `${obj.fontSize * z}px`,
      color: obj.color,
      fontWeight: obj.bold ? "700" : "400",
      textAlign: obj.align ?? "left",
      transformOrigin: "top left",
      transform: obj.rotation ? `rotate(${obj.rotation}deg)` : "none",
      fontFamily: FONT,
      background: "rgba(20,20,20,0.55)",
      border: `1px dashed ${accent()}`,
      outline: "none",
      resize: "both",
      padding: "2px",
      margin: "0",
      overflow: "auto",
      zIndex: "50",
      lineHeight: "1.2",
    } as Partial<CSSStyleDeclaration>);
    container.appendChild(ta);
    ta.focus();
    ta.select();
    editingTextarea = ta;
    let done = false;
    let live: ReturnType<typeof setTimeout> | null = null;
    // the text is kept on every keystroke — a blur is not guaranteed (tab switch, quit)
    ta.addEventListener("input", () => {
      obj.content = ta.value;
      if (live) clearTimeout(live);
      live = setTimeout(() => emitChange(true), 400);
    });
    function commit(): void {
      if (done) return;
      done = true;
      if (live) clearTimeout(live);
      obj.content = ta.value;
      obj.width = Math.max(20, ta.offsetWidth / z);
      obj.height = Math.max(10, ta.offsetHeight / z);
      obj.x = node.x();
      obj.y = node.y();
      obj.rotation = node.rotation();
      applyObjectToNode(obj, node);
      node.show();
      transformer.show();
      ta.remove();
      if (editingTextarea === ta) editingTextarea = null;
      objLayer.batchDraw();
      emitChange(true);
    }
    ta.addEventListener("blur", commit);
    ta.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Escape") {
        ta.value = obj.content;
        commit();
      }
    });
  }

  export function flushTextEdit(): void {
    editingTextarea?.blur();
  }
  export const isTextEditing = (): boolean => editingTextarea !== null;

  function selectOnly(id: string): void {
    selectedIds = new Set([id]);
    applySelection();
  }
  function selectMany(ids: string[]): void {
    selectedIds = new Set(ids);
    applySelection();
  }
  function toggleSelect(id: string): void {
    if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    applySelection();
  }
  export function clearSelection(): void {
    selectedIds = new Set();
    applySelection();
  }
  function applySelection(): void {
    if (!ready) return;
    transformer.nodes([...selectedIds].map((id) => nodesById.get(id)).filter(Boolean) as KNode[]);
    trLayer.batchDraw();
    onselect?.([...selectedIds]);
  }

  function applyStageTransform(): void {
    stage.position({ x: view.x, y: view.y });
    stage.scale({ x: view.zoom, y: view.zoom });
    stage.batchDraw();
    bg = { x: view.x, y: view.y, z: view.zoom };
  }

  function updateCursor(): void {
    if (container) container.style.cursor = tool !== "select" ? "crosshair" : spaceDown ? "grab" : "default";
  }
  $effect(() => {
    void tool;
    updateCursor();
  });

  function init(Kv: Konva): () => void {
    K = Kv;
    const el = container!;
    stage = new K.Stage({ container: el, width: el.clientWidth, height: el.clientHeight });
    objLayer = new K.Layer();
    trLayer = new K.Layer();
    stage.add(objLayer);
    stage.add(trLayer);
    const a = accent();
    transformer = new K.Transformer({
      rotateEnabled: true,
      borderStroke: a,
      anchorStroke: a,
      anchorFill: "#1a1a1a",
      anchorSize: 9,
      borderDash: [4, 4],
    });
    trLayer.add(transformer);
    selectionRect = new K.Rect({ fill: "rgba(255,201,81,0.12)", stroke: a, strokeWidth: 1, visible: false });
    trLayer.add(selectionRect);
    for (const o of [...objs].sort((p, q) => p.zIndex - q.zIndex)) createNode(o);
    ready = true;
    objLayer.batchDraw();
    applyStageTransform();
    updateCursor();

    stage.on("mousedown touchstart", (e) => {
      // a stray focused field (e.g. the sidebar) must not keep keyboard shortcuts away
      const act = document.activeElement as HTMLElement | null;
      if (act && (act.tagName === "INPUT" || act.tagName === "TEXTAREA") && act !== editingTextarea) act.blur();
      if (e.target !== stage) return;
      if (selectedIds.size) clearSelection();
      const pos = stage.getRelativePointerPosition();
      if (!pos) return;
      if (tool === "text") {
        addText(pos, true);
        ontextplaced?.();
        return;
      }
      if (tool === "draw") {
        drawing = true;
        drawPoints = [pos.x, pos.y];
        tempLine = new K.Line({ points: drawPoints, stroke: drawColor, strokeWidth: drawStrokeWidth, lineCap: "round", lineJoin: "round", tension: 0.3 });
        objLayer.add(tempLine);
        return;
      }
      if (tool === "shape") {
        shapeDrawing = true;
        shapeStart = pos;
        const paint = {
          fill: shapeFillTransparent ? "" : shapeFillColor,
          stroke: shapeStrokeTransparent ? "" : shapeStrokeColor,
          strokeWidth: shapeStrokeTransparent ? 0 : shapeStrokeWidth,
        };
        tempShape =
          shapeKind === "ellipse"
            ? new K.Ellipse({ x: pos.x, y: pos.y, radiusX: 0, radiusY: 0, ...paint })
            : new K.Rect({ x: pos.x, y: pos.y, width: 0, height: 0, cornerRadius: shapeCornerRadius, ...paint });
        objLayer.add(tempShape);
        return;
      }
      selecting = true;
      selectStart = pos;
      selectionRect.setAttrs({ x: pos.x, y: pos.y, width: 0, height: 0, visible: true });
    });
    stage.on("mousemove touchmove", (e) => {
      const pos = stage.getRelativePointerPosition();
      if (!pos) return;
      if (drawing && tempLine) {
        drawPoints.push(pos.x, pos.y);
        tempLine.points(drawPoints);
        objLayer.batchDraw();
        return;
      }
      if (shapeDrawing && tempShape) {
        let w = pos.x - shapeStart.x;
        let h = pos.y - shapeStart.y;
        if ((e.evt as MouseEvent).shiftKey) {
          const m = Math.max(Math.abs(w), Math.abs(h));
          w = Math.sign(w || 1) * m;
          h = Math.sign(h || 1) * m;
        }
        const x = Math.min(shapeStart.x, shapeStart.x + w);
        const y = Math.min(shapeStart.y, shapeStart.y + h);
        const aw = Math.abs(w);
        const ah = Math.abs(h);
        if (shapeKind === "ellipse") tempShape.setAttrs({ x: x + aw / 2, y: y + ah / 2, radiusX: aw / 2, radiusY: ah / 2 });
        else tempShape.setAttrs({ x, y, width: aw, height: ah });
        objLayer.batchDraw();
        return;
      }
      if (!selecting) return;
      selectionRect.setAttrs({
        x: Math.min(selectStart.x, pos.x),
        y: Math.min(selectStart.y, pos.y),
        width: Math.abs(pos.x - selectStart.x),
        height: Math.abs(pos.y - selectStart.y),
      });
      trLayer.batchDraw();
    });
    stage.on("mouseup touchend", () => {
      if (drawing) {
        drawing = false;
        tempLine?.destroy();
        tempLine = null;
        if (drawPoints.length >= 4) finalizeDrawing(drawPoints);
        drawPoints = [];
        objLayer.batchDraw();
        return;
      }
      if (shapeDrawing) {
        shapeDrawing = false;
        let box: { x: number; y: number; width: number; height: number } | null = null;
        if (tempShape) {
          const e = tempShape as KonvaNS.Ellipse;
          box =
            shapeKind === "ellipse"
              ? { x: e.x() - e.radiusX(), y: e.y() - e.radiusY(), width: e.radiusX() * 2, height: e.radiusY() * 2 }
              : { x: tempShape.x(), y: tempShape.y(), width: tempShape.width(), height: tempShape.height() };
        }
        tempShape?.destroy();
        tempShape = null;
        if (box && box.width > 3 && box.height > 3) finalizeShape(box.x, box.y, box.width, box.height);
        objLayer.batchDraw();
        return;
      }
      if (!selecting) return;
      selecting = false;
      const box = selectionRect.getClientRect();
      selectionRect.visible(false);
      if (box.width > 2 && box.height > 2) {
        const hits: string[] = [];
        for (const [id, node] of nodesById) if (K.Util.haveIntersection(box, node.getClientRect())) hits.push(id);
        selectMany(hits);
      }
      trLayer.batchDraw();
    });
    stage.on("wheel", (e) => {
      e.evt.preventDefault();
      if (e.evt.ctrlKey || e.evt.metaKey) {
        const p = stage.getPointerPosition();
        if (!p) return;
        const dir = e.evt.deltaY > 0 ? -1 : 1;
        zoomAt(p, Math.max(0.1, Math.min(4, view.zoom * (1 + dir * 0.08 * zoomSensitivity))));
        return;
      }
      view = { ...view, x: view.x - e.evt.deltaX * panSensitivity, y: view.y - e.evt.deltaY * panSensitivity };
      applyStageTransform();
      emitChange();
    });

    const isTyping = () => {
      const t = document.activeElement?.tagName;
      return t === "INPUT" || t === "TEXTAREA";
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isTyping() && el.offsetParent) {
        spaceDown = true;
        stage.draggable(true);
        updateCursor();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      spaceDown = false;
      stage.draggable(false);
      updateCursor();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    stage.on("dragend", (e) => {
      if (e.target !== stage) return;
      view = { ...view, x: stage.x(), y: stage.y() };
      bg = { x: view.x, y: view.y, z: view.zoom };
      emitChange();
    });
    const ro = new ResizeObserver(() => {
      if (!el.clientWidth || !el.clientHeight) return; // hidden tab
      stage.size({ width: el.clientWidth, height: el.clientHeight });
    });
    ro.observe(el);
    // HTML5 drop works in a plain browser; in the app OS drops come through +page.svelte
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      const files = [...(e.dataTransfer?.files ?? [])].filter((f) => f.type.startsWith("image/"));
      if (files.length) ondropfiles?.(files);
    };
    const onOver = (e: DragEvent) => e.preventDefault();
    el.addEventListener("drop", onDrop);
    el.addEventListener("dragover", onOver);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      el.removeEventListener("drop", onDrop);
      el.removeEventListener("dragover", onOver);
      ro.disconnect();
      editingTextarea?.blur();
      stage.destroy();
    };
  }

  onMount(() => {
    let cleanup: (() => void) | null = null;
    let gone = false;
    void import("konva").then((m) => {
      if (!gone) cleanup = init(m.default);
    });
    return () => {
      gone = true;
      cleanup?.();
    };
  });

  function finalizeDrawing(pts: number[]): void {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (let i = 0; i < pts.length; i += 2) {
      x0 = Math.min(x0, pts[i]);
      x1 = Math.max(x1, pts[i]);
      y0 = Math.min(y0, pts[i + 1]);
      y1 = Math.max(y1, pts[i + 1]);
    }
    if (x1 - x0 < 3 && y1 - y0 < 3) return; // a click, not a stroke
    const pad = Math.max(4, drawStrokeWidth);
    const x = x0 - pad;
    const y = y0 - pad;
    const local: number[] = [];
    for (let i = 0; i < pts.length; i += 2) local.push(pts[i] - x, pts[i + 1] - y);
    const obj: DrawObject = {
      id: crypto.randomUUID(),
      type: "draw",
      x,
      y,
      width: Math.max(1, x1 - x0 + pad * 2),
      height: Math.max(1, y1 - y0 + pad * 2),
      rotation: 0,
      opacity: 1,
      zIndex: nextZ(),
      points: local,
      color: drawColor,
      strokeWidth: drawStrokeWidth,
    };
    objs = [...objs, obj];
    createNode(obj);
    objLayer.batchDraw();
    selectOnly(obj.id);
    emitChange(true);
  }

  function finalizeShape(x: number, y: number, width: number, height: number): void {
    const obj: ShapeObject = {
      id: crypto.randomUUID(),
      type: "shape",
      shape: shapeKind,
      x,
      y,
      width,
      height,
      rotation: 0,
      opacity: 1,
      zIndex: nextZ(),
      fillColor: shapeFillColor,
      fillTransparent: shapeFillTransparent,
      strokeColor: shapeStrokeColor,
      strokeWidth: shapeStrokeWidth,
      strokeTransparent: shapeStrokeTransparent,
      cornerRadius: shapeKind === "rect" ? shapeCornerRadius : 0,
    };
    objs = [...objs, obj];
    createNode(obj);
    objLayer.batchDraw();
    selectOnly(obj.id);
    emitChange(true);
  }

  // dotted background with levels of detail: the spacing jumps by powers of two so the
  // dots never shrink to nothing nor balloon (like Miro's grid)
  // svelte-ignore state_referenced_locally
  let bg = $state({ x: viewport.x, y: viewport.y, z: viewport.zoom });
  const dotStep = $derived.by(() => {
    let s = 26;
    while (s * bg.z < 16) s *= 2;
    while (s * bg.z > 42) s /= 2;
    return s * bg.z;
  });
</script>

<div
  bind:this={container}
  class="board"
  style:background-position="{bg.x}px {bg.y}px"
  style:background-size="{dotStep}px {dotStep}px"
></div>

<style>
  .board {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background-color: var(--bg-deep);
    background-image: radial-gradient(rgba(255, 255, 255, 0.16) 1.3px, transparent 1.3px);
  }
</style>
