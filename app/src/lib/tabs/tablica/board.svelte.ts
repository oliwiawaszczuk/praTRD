// Whiteboards (Tablica) — global, independent of workspaces (sidecar: /boards), like in
// praSzczur. A workspace only remembers which board was open last.
//
// Viewport screenshots go through `addImageToBoard`: if the Tablica tab currently shows
// that board, its canvas places the image (so its unsaved state is never overwritten);
// otherwise the board file is updated in the sidecar directly.

import { getJson, sendJson, sidecarBase, tracked } from "#lib/core/api.svelte.ts";
import { browserDownload, inTauri, saveFileDialog } from "#lib/core/tauri.ts";
import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";

export interface BoardMeta {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
}

export type BoardTool = "select" | "draw" | "shape" | "text";
export type ShapeKind = "rect" | "ellipse";
export type TextAlign = "left" | "center" | "right";

interface Base {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
  zIndex: number;
}
export interface ImageObject extends Base {
  type: "image";
  assetUrl: string; // /boards/<id>/assets/<file>
  caption?: string; // e.g. what a viewport screenshot shows
}
export interface TextObject extends Base {
  type: "text";
  content: string;
  color: string;
  fontSize: number;
  bold: boolean;
  align: TextAlign;
  borderEnabled: boolean;
  borderColor: string;
  borderWidth: number;
}
export interface DrawObject extends Base {
  type: "draw";
  points: number[]; // flat [x1, y1, …] relative to (x, y)
  color: string;
  strokeWidth: number;
}
export interface ShapeObject extends Base {
  type: "shape";
  shape: ShapeKind;
  fillColor: string;
  fillTransparent: boolean;
  strokeColor: string;
  strokeWidth: number;
  strokeTransparent: boolean;
  cornerRadius: number;
}
export type BoardObject = ImageObject | TextObject | DrawObject | ShapeObject;

export interface BoardViewport {
  x: number;
  y: number;
  zoom: number;
}
export interface BoardData {
  objects: BoardObject[];
  viewport: BoardViewport;
}

let list = $state<BoardMeta[]>([]);
let loaded = $state(false);

export const boards = (): BoardMeta[] => list;
export const boardsLoaded = (): boolean => loaded;

export async function loadBoards(): Promise<BoardMeta[]> {
  list = (await getJson<{ boards: BoardMeta[] }>("/boards")).boards;
  loaded = true;
  return list;
}
export async function createBoard(name: string): Promise<BoardMeta> {
  const b = await sendJson<BoardMeta>("POST", "/boards", { name });
  await loadBoards();
  return b;
}
export async function renameBoard(id: string, name: string): Promise<void> {
  await sendJson("PUT", `/boards/${id}`, { name });
  await loadBoards();
}
export async function deleteBoard(id: string): Promise<void> {
  await sendJson("DELETE", `/boards/${id}`);
  await loadBoards();
}
export const getBoard = (id: string): Promise<BoardData> => getJson<BoardData>(`/boards/${id}/data`);

let timer: ReturnType<typeof setTimeout> | null = null;
let pending: { id: string; data: BoardData } | null = null;

export function scheduleSaveBoard(id: string, data: BoardData): void {
  if (pending && pending.id !== id) void flushBoard();
  pending = { id, data };
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void flushBoard(), 800);
}

export async function flushBoard(opts: { keepalive?: boolean } = {}): Promise<void> {
  if (timer) clearTimeout(timer);
  timer = null;
  const p = pending;
  pending = null;
  if (!p) return;
  try {
    await sendJson("PUT", `/boards/${p.id}/data`, $state.snapshot(p.data), opts);
    const e = list.find((b) => b.id === p.id);
    if (e) e.updatedAt = new Date().toISOString();
  } catch (e) {
    console.error("[board] save failed", e);
  }
}

export async function uploadAsset(boardId: string, blob: Blob, ext = "png"): Promise<string> {
  const r = await tracked(fetch(`${sidecarBase()}/boards/${boardId}/assets?ext=${ext}`, { method: "POST", body: blob }));
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? "Nie udało się zapisać obrazu");
  return ((await r.json()) as { url: string }).url;
}

export async function assetFromPath(boardId: string, path: string): Promise<string> {
  return (await sendJson<{ url: string }>("POST", `/boards/${boardId}/assets/from-path`, { path })).url;
}

export const assetUrl = (url: string): string => `${sidecarBase()}${url}`;

// ── the board currently open in the Tablica tab (screenshots land there live) ──
type Placer = (assetUrl: string, w: number, h: number, caption: string) => void;
let live: { boardId: string; place: Placer } | null = null;

export function registerLiveBoard(boardId: string | null, place: Placer | null): void {
  live = boardId && place ? { boardId, place } : null;
}

/** The board screenshots go to: the last opened one (per workspace), else the first, else
 * a new "Tablica 1". */
export async function targetBoard(): Promise<BoardMeta> {
  if (!loaded) await loadBoards();
  const saved = wsGet<string>("tablica_activeBoardId", "");
  const b = list.find((x) => x.id === saved) ?? list[0];
  if (b) return b;
  const n = await createBoard("Tablica 1");
  wsSet("tablica_activeBoardId", n.id);
  return n;
}

/** A picture (e.g. a viewport screenshot) onto the target board; returns its name. */
export async function addImageToBoard(blob: Blob, w: number, h: number, caption: string): Promise<string> {
  const b = await targetBoard();
  const url = await uploadAsset(b.id, blob);
  if (live?.boardId === b.id) {
    live.place(url, w, h, caption);
    return b.name;
  }
  await flushBoard(); // never race a pending save of the same board
  const data = await getBoard(b.id);
  const z = data.objects.reduce((m, o) => Math.max(m, o.zIndex), -1) + 1;
  // to the right of everything already there, top-aligned
  const right = data.objects.reduce((m, o) => Math.max(m, o.x + o.width), 0);
  const top = data.objects.length ? Math.min(...data.objects.map((o) => o.y)) : 0;
  const scale = Math.min(1, 480 / Math.max(w, h));
  const img: ImageObject = {
    id: crypto.randomUUID(),
    type: "image",
    assetUrl: url,
    caption,
    x: data.objects.length ? right + 40 : 0,
    y: top,
    width: w * scale,
    height: h * scale,
    rotation: 0,
    opacity: 1,
    zIndex: z,
  };
  data.objects.push(img);
  if (caption) {
    // the same visible caption the live canvas adds (BoardCanvas.placeImage)
    data.objects.push({
      id: crypto.randomUUID(),
      type: "text",
      content: caption,
      x: img.x,
      y: img.y + img.height + 8,
      width: img.width,
      height: 24,
      rotation: 0,
      opacity: 1,
      zIndex: z + 1,
      color: "#bbbbbb",
      fontSize: 14,
      bold: false,
      align: "left",
      borderEnabled: false,
      borderColor: "#000000",
      borderWidth: 1.5,
    });
  }
  await sendJson("PUT", `/boards/${b.id}/data`, data);
  await loadBoards();
  return b.name;
}

// OS file drops while the Tablica tab is shown (the webview only gets paths)
let dropHandler: ((paths: string[]) => void) | null = null;
export function registerBoardDrop(fn: ((paths: string[]) => void) | null): void {
  dropHandler = fn;
}
/** true when the board took the drop (images only). */
export function dropOnBoard(paths: string[]): boolean {
  const imgs = paths.filter((p) => /\.(png|jpe?g|gif|webp|bmp)$/i.test(p));
  if (!dropHandler || !imgs.length) return false;
  dropHandler(imgs);
  return true;
}

export async function savePng(blob: Blob, name: string): Promise<string | null> {
  if (!inTauri()) {
    browserDownload(blob, name);
    return name;
  }
  const path = await saveFileDialog(name, "png", "Obraz PNG");
  if (!path) return null;
  const r = await tracked(fetch(`${sidecarBase()}/export/png?path=${encodeURIComponent(path)}`, { method: "POST", body: blob }));
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? "Nie udało się zapisać PNG");
  return path;
}
