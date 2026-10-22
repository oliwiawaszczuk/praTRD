// Per-workspace UI state (same contract as praSzczur):
//   anything that should survive a restart or differ between workspaces goes through
//   wsGet(key, fallback) / wsSet(key, value) — never localStorage or module variables.
// The whole map is saved (debounced 500 ms) to /workspaces/{id}/settings.

import { getJson, sendJson } from "./api.svelte.ts";
import { debouncedSaver } from "./persisted.ts";

export interface WorkspaceMeta {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
}

interface Registry {
  active_id: string;
  workspaces: WorkspaceMeta[];
}

let cache = $state<Record<string, unknown>>({});
let list = $state<WorkspaceMeta[]>([]);
let activeId = $state("");

// $state.snapshot: serialize a plain object, not the reactive proxy.
const saver = debouncedSaver(500, ({ keepalive }) =>
  activeId
    ? sendJson("PUT", `/workspaces/${activeId}/settings`, $state.snapshot(cache), { keepalive })
    : Promise.resolve(),
);

export async function loadWorkspaces(): Promise<void> {
  const reg = await getJson<Registry>("/workspaces");
  list = reg.workspaces;
  activeId = reg.active_id;
  cache = await getJson<Record<string, unknown>>(`/workspaces/${activeId}/settings`);
}

async function refreshList(): Promise<void> {
  const reg = await getJson<Registry>("/workspaces");
  list = reg.workspaces;
}

export function wsGet<T>(key: string, fallback: T): T {
  return key in cache ? (cache[key] as T) : fallback;
}

export function wsSet(key: string, value: unknown): void {
  // Skip no-op writes of primitives; objects are always saved (callers may pass a
  // mutated copy, and a proxy never === its raw source anyway).
  if (typeof value !== "object" && cache[key] === value) return;
  cache[key] = value;
  saver.schedule();
}

export const flushWorkspace = saver.flush;

export const workspaces = (): WorkspaceMeta[] => list;
export const activeWorkspaceId = (): string => activeId;
export const activeWorkspace = (): WorkspaceMeta | undefined => list.find((w) => w.id === activeId);

/** Switching reloads the page: every store re-reads its state for the new workspace,
 * no stale per-workspace data can leak across. */
export async function switchWorkspace(id: string): Promise<void> {
  await saver.flush();
  await sendJson("POST", `/workspaces/${id}/activate`);
  location.reload();
}

export async function createWorkspace(name: string): Promise<void> {
  const ws = await sendJson<WorkspaceMeta>("POST", "/workspaces", { name });
  await switchWorkspace(ws.id);
}

export async function renameWorkspace(id: string, name: string): Promise<void> {
  await sendJson("PUT", `/workspaces/${id}`, { name });
  await refreshList();
}

export async function deleteWorkspace(id: string): Promise<void> {
  await sendJson("DELETE", `/workspaces/${id}`);
  if (id === activeId) location.reload();
  else await refreshList();
}

export async function exportWorkspace(id: string, destDir: string): Promise<string> {
  await saver.flush();
  const r = await sendJson<{ path: string }>("POST", `/workspaces/${id}/export`, { dest_dir: destDir });
  return r.path;
}

export async function importWorkspace(srcDir: string): Promise<void> {
  const ws = await sendJson<WorkspaceMeta>("POST", "/workspaces/import", { src_dir: srcDir });
  await switchWorkspace(ws.id);
}
