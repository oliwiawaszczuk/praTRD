// Graphs of the active workspace: list, active document, mutations, undo/redo, selection.
//
// * Autosave: 300 ms after the last change (praSzczur pattern), flushed on graph switch.
// * Undo: snapshots of the document taken at COMMIT points (end of a drag, a param edit
//   burst, an added edge…), never per pointer-move — so undo steps match user actions.

import { getJson, sendJson } from "#lib/core/api.svelte.ts";
import { debouncedSaver } from "#lib/core/persisted.ts";
import { activeWorkspaceId, wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
import { defaultParams, nodeType } from "./registry.svelte.ts";
import type { GEdge, GNode, GraphDoc, GraphMeta } from "./types.ts";

const UNDO_MAX = 100;

let graphs = $state<GraphMeta[]>([]);
let activeId = $state("");
let doc = $state<GraphDoc>({ nodes: [], edges: [], view: { x: 40, y: 30, zoom: 1 } });
let loaded = $state(false);
let selection = $state<Set<string>>(new Set());

let undoStack: string[] = [];
let redoStack: string[] = [];
let undoLen = $state(0);
let redoLen = $state(0);
let lastCommitted = "";

const wsPath = () => `/workspaces/${activeWorkspaceId()}/graphs`;

const saver = debouncedSaver(300, ({ keepalive }) =>
  activeId ? sendJson("PUT", `${wsPath()}/${activeId}/doc`, $state.snapshot(doc), { keepalive }) : Promise.resolve(),
);
export const flushGraph = saver.flush;

const uid = () => Math.random().toString(36).slice(2, 10);

export const graph = {
  get list() {
    return graphs;
  },
  get activeId() {
    return activeId;
  },
  get doc() {
    return doc;
  },
  get loaded() {
    return loaded;
  },
  get selection() {
    return selection;
  },
  get canUndo() {
    return undoLen > 0;
  },
  get canRedo() {
    return redoLen > 0;
  },
};

export async function loadGraphs(): Promise<void> {
  graphs = await getJson<GraphMeta[]>(wsPath());
  const want = wsGet<string>("graph_active", "");
  await openGraph(graphs.some((g) => g.id === want) ? want : graphs[0].id);
}

export async function openGraph(id: string): Promise<void> {
  await saver.flush();
  const d = await getJson<GraphDoc>(`${wsPath()}/${id}/doc`);
  d.view ??= { x: 40, y: 30, zoom: 1 };
  activeId = id;
  doc = d;
  selection = new Set();
  undoStack = [];
  redoStack = [];
  undoLen = redoLen = 0;
  lastCommitted = JSON.stringify(d);
  loaded = true;
  wsSet("graph_active", id);
}

export async function createGraph(name: string): Promise<void> {
  const g = await sendJson<GraphMeta>("POST", wsPath(), { name });
  graphs = [...graphs, g];
  await openGraph(g.id);
}

export async function renameGraph(id: string, name: string): Promise<void> {
  const g = await sendJson<GraphMeta>("PUT", `${wsPath()}/${id}`, { name });
  graphs = graphs.map((x) => (x.id === id ? g : x));
}

export async function deleteGraph(id: string): Promise<void> {
  await sendJson("DELETE", `${wsPath()}/${id}`);
  graphs = graphs.filter((g) => g.id !== id);
  if (id === activeId) await openGraph(graphs[0].id);
}

// ── mutations ───────────────────────────────────────────────────────────────

/** Record an undo step if the document changed since the last commit, then save. */
export function commit(): void {
  const now = JSON.stringify($state.snapshot(doc));
  if (now === lastCommitted) return;
  undoStack.push(lastCommitted);
  if (undoStack.length > UNDO_MAX) undoStack.shift();
  redoStack = [];
  undoLen = undoStack.length;
  redoLen = 0;
  lastCommitted = now;
  saver.schedule();
}

/** View changes (pan/zoom) are saved but are not undo steps. */
export function setView(v: GraphDoc["view"]): void {
  doc.view = v;
  saver.schedule();
}

function restore(json: string): void {
  doc = JSON.parse(json);
  lastCommitted = json;
  const ids = new Set(doc.nodes.map((n) => n.id));
  selection = new Set([...selection].filter((id) => ids.has(id)));
  saver.schedule();
}

export function undo(): void {
  const prev = undoStack.pop();
  if (!prev) return;
  redoStack.push(lastCommitted);
  restore(prev);
  undoLen = undoStack.length;
  redoLen = redoStack.length;
}

export function redo(): void {
  const next = redoStack.pop();
  if (!next) return;
  undoStack.push(lastCommitted);
  restore(next);
  undoLen = undoStack.length;
  redoLen = redoStack.length;
}

export function addNode(typeId: string, x: number, y: number, params?: Record<string, unknown>): GNode | null {
  const t = nodeType(typeId);
  if (!t) return null;
  const n: GNode = { id: uid(), type: typeId, x: Math.round(x), y: Math.round(y), params: { ...defaultParams(t), ...params } };
  doc.nodes.push(n);
  selection = new Set([n.id]);
  commit();
  return n;
}

export function nodeById(id: string): GNode | undefined {
  return doc.nodes.find((n) => n.id === id);
}

export function setParam(nodeId: string, key: string, value: unknown): void {
  const n = nodeById(nodeId);
  if (!n) return;
  n.params[key] = value;
  paramCommit();
}

// a slider drag produces dozens of changes — one undo step per burst
let paramTimer: ReturnType<typeof setTimeout> | null = null;
function paramCommit(): void {
  if (paramTimer) clearTimeout(paramTimer);
  paramTimer = setTimeout(commit, 400);
}

export function moveNodes(ids: Iterable<string>, dx: number, dy: number, origin: Map<string, [number, number]>): void {
  for (const id of ids) {
    const n = nodeById(id);
    const o = origin.get(id);
    if (n && o) {
      n.x = Math.round(o[0] + dx);
      n.y = Math.round(o[1] + dy);
    }
  }
}

/** Typed connection: replaces whatever fed a single (non-multi) input. */
export function connect(from: string, fromSocket: string, to: string, toSocket: string): boolean {
  if (from === to) return false;
  const a = nodeById(from);
  const b = nodeById(to);
  const ta = a && nodeType(a.type);
  const tb = b && nodeType(b.type);
  const out = ta?.outputs.find((p) => p.id === fromSocket);
  const inp = tb?.inputs.find((p) => p.id === toSocket);
  if (!out || !inp || out.kind !== inp.kind) return false;
  if (wouldCycle(from, to)) return false;
  if (doc.edges.some((e) => e.from === from && e.fromSocket === fromSocket && e.to === to && e.toSocket === toSocket))
    return false;
  if (!inp.multi) doc.edges = doc.edges.filter((e) => !(e.to === to && e.toSocket === toSocket));
  doc.edges.push({ id: uid(), from, fromSocket, to, toSocket });
  commit();
  return true;
}

/** Would an edge from → to close a cycle (is `from` reachable from `to`)? */
export function wouldCycle(from: string, to: string): boolean {
  const stack = [to];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === from) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of doc.edges) if (e.from === cur) stack.push(e.to);
  }
  return false;
}

export function removeEdge(id: string): void {
  doc.edges = doc.edges.filter((e) => e.id !== id);
  commit();
}

export function deleteNodes(ids: Set<string>): void {
  doc.nodes = doc.nodes.filter((n) => !ids.has(n.id));
  doc.edges = doc.edges.filter((e) => !ids.has(e.from) && !ids.has(e.to));
  if (doc.display && ids.has(doc.display)) doc.display = null;
  selection = new Set();
  commit();
}

export function setDisplay(nodeId: string | null): void {
  doc.display = nodeId;
  commit();
}

export function select(ids: Iterable<string>, additive = false): void {
  selection = additive ? new Set([...selection, ...ids]) : new Set(ids);
}

export function toggleSelect(id: string): void {
  const s = new Set(selection);
  if (s.has(id)) s.delete(id);
  else s.add(id);
  selection = s;
}

// ── clipboard (copy/paste of a sub-graph, internal edges included) ─────────────

export function serializeSelection(): string | null {
  if (!selection.size) return null;
  const nodes = doc.nodes.filter((n) => selection.has(n.id));
  const edges = doc.edges.filter((e) => selection.has(e.from) && selection.has(e.to));
  return JSON.stringify({ pratrdGraph: 1, nodes, edges });
}

export function pasteGraph(text: string, at: [number, number]): boolean {
  let data: { pratrdGraph?: number; nodes: GNode[]; edges: GEdge[] };
  try {
    data = JSON.parse(text);
  } catch {
    return false;
  }
  if (data?.pratrdGraph !== 1 || !Array.isArray(data.nodes) || !data.nodes.length) return false;
  const minX = Math.min(...data.nodes.map((n) => n.x));
  const minY = Math.min(...data.nodes.map((n) => n.y));
  const map = new Map<string, string>();
  for (const n of data.nodes) {
    if (!nodeType(n.type)) continue;
    const id = uid();
    map.set(n.id, id);
    doc.nodes.push({ ...n, id, x: Math.round(n.x - minX + at[0]), y: Math.round(n.y - minY + at[1]) });
  }
  for (const e of data.edges)
    if (map.has(e.from) && map.has(e.to)) doc.edges.push({ ...e, id: uid(), from: map.get(e.from)!, to: map.get(e.to)! });
  selection = new Set(map.values());
  commit();
  return true;
}
