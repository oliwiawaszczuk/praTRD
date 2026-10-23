// Notes — global, independent of workspaces (sidecar: /notes). The list carries title and
// preview; a note's text is fetched when opened and saved debounced (800 ms).

import { getJson, sendJson } from "#lib/core/api.svelte.ts";

export interface NoteMeta {
  id: string;
  title: string;
  titleManual: boolean;
  preview: string;
  createdAt: string;
  updatedAt: string;
}

let list = $state<NoteMeta[]>([]);
let loaded = $state(false);

export const notes = (): NoteMeta[] => list;
export const notesLoaded = (): boolean => loaded;

export async function loadNotes(): Promise<NoteMeta[]> {
  list = (await getJson<{ notes: NoteMeta[] }>("/notes")).notes;
  loaded = true;
  return list;
}

export async function createNote(title = "Nowa notatka"): Promise<NoteMeta> {
  const n = await sendJson<NoteMeta>("POST", "/notes", { title });
  await loadNotes();
  return n;
}

export async function renameNote(id: string, title: string): Promise<void> {
  await sendJson("PUT", `/notes/${id}`, { title });
  await loadNotes();
}

export async function deleteNote(id: string): Promise<void> {
  await sendJson("DELETE", `/notes/${id}`);
  await loadNotes();
}

export async function getNote(id: string): Promise<string> {
  return (await getJson<{ text: string }>(`/notes/${id}/data`)).text;
}

let timer: ReturnType<typeof setTimeout> | null = null;
let pending: { id: string; text: string } | null = null;

export function scheduleSaveNote(id: string, text: string): void {
  if (pending && pending.id !== id) void flushNote(); // another note: save that one first
  pending = { id, text };
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void flushNote(), 800);
}

export async function flushNote(opts: { keepalive?: boolean } = {}): Promise<void> {
  if (timer) clearTimeout(timer);
  timer = null;
  const p = pending;
  pending = null;
  if (!p) return;
  try {
    const r = await sendJson<{ title: string }>("PUT", `/notes/${p.id}/data`, { text: p.text }, opts);
    const e = list.find((n) => n.id === p.id);
    if (e) {
      e.updatedAt = new Date().toISOString();
      e.preview = p.text.trim().slice(0, 300);
      e.title = r.title;
    }
  } catch (e) {
    console.error("[notes] save failed", e);
  }
}
