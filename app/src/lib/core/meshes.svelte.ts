// Meshes: the workspace's imported files (STL / OBJ / PLY) and binary geometry of any mesh
// (library or node result) for the viewports. Buffers come straight from the sidecar files
// (verts | normals | VTK cells) — views over ONE ArrayBuffer, no conversion.

import { getJson, sendJson, sidecarBase, tracked } from "./api.svelte.ts";
import { onEvent } from "./events.svelte.ts";
import { inTauri } from "./tauri.ts";
import { activeWorkspaceId } from "./workspace.svelte.ts";

export interface MeshEntry {
  id: string;
  name: string;
  file: string;
  format: string;
  space: "LPS" | "RAS";
  spaceFromFile: boolean;
  verts: number;
  faces: number;
  area: number;
  ml: number;
  closed: boolean;
  bounds: number[];
  createdAt: string;
}

export interface MeshData {
  ref: string;
  verts: Float32Array; // [N·3] world LPS mm
  normals: Float32Array; // [N·3]
  cells: Uint32Array; // [M·4] (3, a, b, c)
  nVerts: number;
  nFaces: number;
  bounds: number[]; // xmin, xmax, ymin, ymax, zmin, zmax
  lod: boolean; // a decimated display copy (the node result has more triangles)
}

export const MESH_EXTENSIONS = ["stl", "obj", "ply"];
export const isMeshPath = (p: string): boolean => MESH_EXTENSIONS.includes(p.split(".").pop()?.toLowerCase() ?? "");

const wsPath = () => `/workspaces/${activeWorkspaceId()}`;

let entries = $state<MeshEntry[]>([]);
let loaded = false;

export async function loadMeshes(): Promise<void> {
  entries = await getJson<MeshEntry[]>(`${wsPath()}/meshes`);
  loaded = true;
}

onEvent("meshes-changed", (m) => {
  if (m.wid === activeWorkspaceId()) void loadMeshes();
});

/** Library meshes (loaded on first use). */
export function libraryMeshes(): MeshEntry[] {
  if (!loaded) {
    loaded = true;
    void loadMeshes().catch(() => (loaded = false));
  }
  return entries;
}

export async function importMeshes(paths: string[]): Promise<{ added: MeshEntry[]; errors: { path: string; error: string }[] }> {
  const r = await sendJson<{ added: MeshEntry[]; errors: { path: string; error: string }[] }>("POST", `${wsPath()}/meshes/import`, { paths });
  if (r.added.length) await loadMeshes();
  return r;
}

export async function deleteMesh(mid: string): Promise<void> {
  await sendJson("DELETE", `${wsPath()}/meshes/${mid}`);
  entries = entries.filter((e) => e.id !== mid);
}

export const meshThumbUrl = (ref: string): string => `${sidecarBase()}${wsPath()}/meshes/${ref}/thumb.png`;

// ── geometry ──
// A small LRU: switching the displayed node back and forth never re-downloads.
const CACHE_BYTES = 256 << 20;
const cache = new Map<string, MeshData>();
const inflight = new Map<string, Promise<MeshData>>();

function remember(key: string, d: MeshData): void {
  cache.delete(key);
  cache.set(key, d);
  let total = 0;
  for (const v of cache.values()) total += v.verts.byteLength * 2 + v.cells.byteLength;
  for (const [k, v] of cache) {
    if (total <= CACHE_BYTES || cache.size <= 1) break;
    total -= v.verts.byteLength * 2 + v.cells.byteLength;
    cache.delete(k);
  }
}

/** Geometry of a mesh (shared by every view; meshes are immutable per ref). */
export function fetchMesh(ref: string): Promise<MeshData> {
  const key = `${activeWorkspaceId()}:${ref}`;
  const hit = cache.get(key);
  if (hit) {
    remember(key, hit);
    return Promise.resolve(hit);
  }
  let p = inflight.get(key);
  if (!p) {
    p = (async () => {
      const r = await tracked(fetch(`${sidecarBase()}${wsPath()}/meshes/${ref}/data`));
      if (!r.ok) throw new Error(`Nie udało się wczytać mesha (${r.status})`);
      const meta = JSON.parse(r.headers.get("X-Meta") ?? "{}") as { verts: number; faces: number; bounds: number[]; lod?: boolean };
      const buf = await r.arrayBuffer();
      const n = meta.verts;
      const d: MeshData = {
        ref,
        verts: new Float32Array(buf, 0, n * 3),
        normals: new Float32Array(buf, n * 12, n * 3),
        cells: new Uint32Array(buf, n * 24, meta.faces * 4),
        nVerts: n,
        nFaces: meta.faces,
        bounds: meta.bounds,
        lod: !!meta.lod,
      };
      remember(key, d);
      return d;
    })().finally(() => inflight.delete(key));
    inflight.set(key, p);
  }
  return p;
}

/** Native "Save as" (STL / OBJ / PLY by the chosen extension); the sidecar writes the file. */
export async function exportMesh(ref: string, name: string, space: "LPS" | "RAS" = "LPS"): Promise<string | null> {
  if (!inTauri()) return null;
  const { save } = await import("@tauri-apps/plugin-dialog");
  const base = (name || "mesh").replace(/[\\/:*?"<>|·]+/g, "-").replace(/\s+-\s+/g, "-").trim();
  const path = await save({
    title: "Eksport mesha",
    defaultPath: `${base}.stl`,
    filters: [
      { name: "STL (binarny)", extensions: ["stl"] },
      { name: "OBJ", extensions: ["obj"] },
      { name: "PLY (binarny)", extensions: ["ply"] },
    ],
  });
  if (!path) return null;
  const full = isMeshPath(path) ? path : `${path}.stl`;
  await sendJson("POST", `${wsPath()}/meshes/${ref}/export`, { path: full, space });
  return full;
}
