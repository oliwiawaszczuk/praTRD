// Whole pyramid levels for the 3-D view, streamed into ONE preallocated buffer
// (Content-Length is known), with progress. No arrayBuffer() double-buffering.

import { sidecarBase, tracked } from "#lib/core/api.svelte.ts";
import type { Voxels } from "./slices.ts";

export interface LevelData {
  shape: [number, number, number]; // [k, j, i]
  dtype: string;
  data: Voxels;
}

const VIEWS: Record<string, { new (b: ArrayBuffer): Voxels; BYTES_PER_ELEMENT: number }> = {
  int16: Int16Array,
  uint16: Uint16Array,
  int32: Int32Array,
  uint8: Uint8Array,
  float32: Float32Array,
};

export async function fetchLevel(
  volumePath: string,
  level: number,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<LevelData> {
  const r = await tracked(fetch(`${sidecarBase()}${volumePath}/level/${level}`, { signal }));
  if (!r.ok || !r.body) throw new Error(`Nie udało się wczytać poziomu ${level} (${r.status})`);
  const meta = JSON.parse(r.headers.get("X-Meta") ?? "{}") as { shape: [number, number, number]; dtype: string };
  const total = Number(r.headers.get("Content-Length"));
  const View = VIEWS[meta.dtype];
  if (!View) throw new Error(`Nieobsługiwany typ danych: ${meta.dtype}`);

  const buf = new ArrayBuffer(total);
  const bytes = new Uint8Array(buf);
  const reader = r.body.getReader();
  let off = 0;
  let lastReport = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes.set(value, off);
    off += value.byteLength;
    const now = performance.now();
    if (now - lastReport > 50) {
      lastReport = now;
      onProgress(off / total);
    }
  }
  if (off !== total) throw new Error(`Niepełne dane (${off}/${total} B)`);
  onProgress(1);
  return { shape: meta.shape, dtype: meta.dtype, data: new View(buf) };
}
