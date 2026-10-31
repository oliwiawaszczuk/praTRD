// Folders of the Dane tab: a per-workspace grouping of library volumes (UI state only —
// the library itself stays flat). A volume is in at most one folder; "" = no folder.

import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";

export interface Folder {
  id: string;
  name: string;
}

export const ALL = "*"; // pseudo-folder: every volume
export const LOOSE = ""; // pseudo-folder: volumes in no folder

let folders = $state<Folder[]>(wsGet<Folder[]>("dane_folders", []));
let assign = $state<Record<string, string>>(wsGet<Record<string, string>>("dane_folderOf", {}));
let current = $state<string>(wsGet<string>("dane_folder", ALL));
// volumes present when an import started: whatever appears later goes to `target`
let importing: { target: string; known: Set<string> } | null = null;

export const danePanel = {
  get folders() {
    return folders;
  },
  get current() {
    return current;
  },
};

export const folderOf = (vid: string): string => assign[vid] ?? LOOSE;

export function inFolder(vid: string, folder: string): boolean {
  return folder === ALL || folderOf(vid) === folder;
}

export function openFolder(id: string): void {
  current = id;
  wsSet("dane_folder", id);
}

export function addFolder(name: string): void {
  const f = { id: Math.random().toString(36).slice(2, 10), name };
  folders = [...folders, f];
  wsSet("dane_folders", $state.snapshot(folders));
  openFolder(f.id);
}

export function renameFolder(id: string, name: string): void {
  folders = folders.map((f) => (f.id === id ? { ...f, name } : f));
  wsSet("dane_folders", $state.snapshot(folders));
}

/** Remove a folder; its volumes become loose (never deleted). */
export function removeFolder(id: string): void {
  folders = folders.filter((f) => f.id !== id);
  assign = Object.fromEntries(Object.entries(assign).filter(([, f]) => f !== id));
  wsSet("dane_folders", $state.snapshot(folders));
  wsSet("dane_folderOf", $state.snapshot(assign));
  if (current === id) openFolder(ALL);
}

export function moveToFolder(vid: string, folder: string): void {
  const next = { ...assign };
  if (folder === LOOSE || folder === ALL) delete next[vid];
  else next[vid] = folder;
  assign = next;
  wsSet("dane_folderOf", next);
}

/** Call before an import: volumes it adds land in the folder open now. */
export function noteImport(knownIds: string[]): void {
  importing = current === ALL || current === LOOSE ? null : { target: current, known: new Set(knownIds) };
}

/** Library changed: put freshly imported volumes into the import's folder. */
export function claimNew(ids: string[]): void {
  if (!importing) return;
  const { target, known } = importing;
  let next: Record<string, string> | null = null;
  for (const id of ids)
    if (!known.has(id) && !(id in assign)) {
      next ??= { ...assign };
      next[id] = target;
      known.add(id);
    }
  if (!next || !folders.some((f) => f.id === target)) return;
  assign = next;
  wsSet("dane_folderOf", next);
}
