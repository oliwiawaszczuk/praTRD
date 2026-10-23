// User documentation — global (sidecar: /app_docs): guide text per app tab, the user's own
// pages, and OVERRIDES of node-type descriptions. A node's description is read through
// nodeDoc() both here and by the "(i)" on node cards, so an edit shows up in both places.

import { getJson, sendJson } from "#lib/core/api.svelte.ts";
import { debouncedSaver } from "#lib/core/persisted.ts";

export interface DocPage {
  id: string;
  title: string;
  body: string;
}
interface Docs {
  tabs: Record<string, string>;
  nodes: Record<string, string>;
  pages: DocPage[];
}

let data = $state<Docs>({ tabs: {}, nodes: {}, pages: [] });
let loaded = $state(false);
const saver = debouncedSaver(500, ({ keepalive }) => sendJson("PUT", "/app_docs", $state.snapshot(data), { keepalive }));

export const appDocsLoaded = () => loaded;
export const flushAppDocs = saver.flush;

export async function loadAppDocs(): Promise<void> {
  try {
    data = await getJson<Docs>("/app_docs");
  } catch {
    // keep defaults — the docs tab still shows the built-in guide
  }
  loaded = true;
}

export const tabDoc = (key: string): string => data.tabs[key] ?? "";
export function setTabDoc(key: string, body: string): void {
  data.tabs[key] = body;
  saver.schedule();
}
export function clearTabDoc(key: string): void {
  delete data.tabs[key];
  saver.schedule();
}

/** A node type's description: the user's override, else the one from the sidecar. */
export const nodeDoc = (typeId: string, fallback: string): string => (data.nodes[typeId]?.trim() ? data.nodes[typeId] : fallback);
export const hasNodeDoc = (typeId: string): boolean => !!data.nodes[typeId]?.trim();
export function setNodeDoc(typeId: string, body: string): void {
  data.nodes[typeId] = body;
  saver.schedule();
}
export function clearNodeDoc(typeId: string): void {
  delete data.nodes[typeId];
  saver.schedule();
}

export const docPages = (): DocPage[] => data.pages;
export function createPage(title = "Nowa strona"): DocPage {
  const p = { id: crypto.randomUUID(), title, body: "" };
  data.pages.push(p);
  saver.schedule();
  return p;
}
export function updatePage(id: string, patch: Partial<Omit<DocPage, "id">>): void {
  const p = data.pages.find((x) => x.id === id);
  if (!p) return;
  Object.assign(p, patch);
  saver.schedule();
}
export function deletePage(id: string): void {
  data.pages = data.pages.filter((p) => p.id !== id);
  saver.schedule();
}
export function movePage(from: number, to: number): void {
  if (from === to) return;
  const [m] = data.pages.splice(from, 1);
  data.pages.splice(to, 0, m);
  saver.schedule();
}

// "(i)" on a node card → this tab, at that node
export type DocSection = { kind: "tab"; key: string } | { kind: "node"; typeId: string } | { kind: "page"; id: string };
let pendingSection = $state<DocSection | null>(null);
export function requestDocSection(s: DocSection): void {
  pendingSection = s;
}
export function takeDocSection(): DocSection | null {
  const s = pendingSection;
  if (s) pendingSection = null;
  return s;
}
