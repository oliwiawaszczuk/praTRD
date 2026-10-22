// Slice fetching + windowing, framework-free (shared later by the E2 viewports).

import { getBinary } from "#lib/core/api.svelte.ts";
import type { Axis } from "#lib/core/library.svelte.ts";

export type Voxels = Int16Array | Uint16Array | Int32Array | Uint8Array | Float32Array;

export interface Slice {
  rows: number;
  cols: number;
  data: Voxels;
}

const VIEWS: Record<string, new (b: ArrayBuffer) => Voxels> = {
  int16: Int16Array,
  uint16: Uint16Array,
  int32: Int32Array,
  uint8: Uint8Array,
  float32: Float32Array,
};

/** Byte-bounded LRU of decoded slices: scrolling back over seen slices costs nothing. */
class SliceCache {
  private map = new Map<string, Slice>();
  private bytes = 0;
  constructor(private readonly maxBytes: number) {}

  get(key: string): Slice | undefined {
    const s = this.map.get(key);
    if (s) {
      this.map.delete(key);
      this.map.set(key, s);
    }
    return s;
  }

  set(key: string, s: Slice): void {
    this.map.set(key, s);
    this.bytes += s.data.byteLength;
    for (const [k, v] of this.map) {
      if (this.bytes <= this.maxBytes) break;
      this.map.delete(k);
      this.bytes -= v.data.byteLength;
    }
  }
}

const cache = new SliceCache(96 << 20);

export async function fetchSlice(
  volumePath: string,
  axis: Axis,
  index: number,
  level: number,
  signal?: AbortSignal,
): Promise<Slice> {
  const key = `${volumePath}|${level}|${axis}|${index}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const { meta, buffer } = await getBinary<{ shape: [number, number]; dtype: string }>(
    `${volumePath}/slice?axis=${axis}&index=${index}&level=${level}`,
    signal,
  );
  const View = VIEWS[meta.dtype];
  if (!View) throw new Error(`Nieobsługiwany typ danych: ${meta.dtype}`);
  const s: Slice = { rows: meta.shape[0], cols: meta.shape[1], data: new View(buffer) };
  cache.set(key, s);
  return s;
}

/** Window/level → opaque grey RGBA, written as packed uint32 (one store per pixel).
 * Integer data with a modest value range goes through a byte LUT (one load per pixel). */
export function windowToRgba(
  s: Slice,
  center: number,
  width: number,
  out: Uint32Array,
  range: { min: number; max: number },
): void {
  const lo = center - width / 2;
  const scale = 255 / Math.max(width, 1e-9);
  const n = s.rows * s.cols;
  const d = s.data;
  const span = range.max - range.min;
  if (!(d instanceof Float32Array) && span >= 0 && span <= 1 << 20) {
    const min = range.min;
    const lut = new Uint32Array(span + 1);
    for (let v = 0; v <= span; v++) {
      let g = ((v + min - lo) * scale) | 0;
      g = g < 0 ? 0 : g > 255 ? 255 : g;
      lut[v] = 0xff000000 | (g << 16) | (g << 8) | g;
    }
    for (let p = 0; p < n; p++) {
      let idx = d[p] - min;
      idx = idx < 0 ? 0 : idx > span ? span : idx;
      out[p] = lut[idx];
    }
    return;
  }
  for (let p = 0; p < n; p++) {
    let g = ((d[p] - lo) * scale) | 0;
    g = g < 0 ? 0 : g > 255 ? 255 : g;
    out[p] = 0xff000000 | (g << 16) | (g << 8) | g;
  }
}

export interface SliceRequest {
  path: string; // volumePath(vid)
  axis: Axis;
  index: number;
  level: number;
}

const keyOf = (r: SliceRequest) => `${r.path}|${r.level}|${r.axis}|${r.index}`;

export function peekSlice(r: SliceRequest): Slice | undefined {
  return cache.get(keyOf(r));
}

/** Single-flight, latest-wins slice loading for one view.
 *
 * At most one request is in flight; while it runs, newer requests only replace the
 * "pending" slot. A finished slice is always delivered (it is closer to the target than
 * what is on screen), then the latest pending one is fetched — so fast scrolling never
 * starves and never queues stale work. When idle, neighbours in the scroll direction are
 * prefetched into the shared cache (the sidecar serves them from its chunk cache, ~1 ms). */
export class SliceLoader {
  private inflight: SliceRequest | null = null;
  private pending: SliceRequest | null = null;
  private prefetchQueue: SliceRequest[] = [];
  private disposed = false;

  constructor(
    private readonly deliver: (s: Slice, r: SliceRequest) => void,
    private readonly onError: (e: unknown) => void = () => {},
  ) {}

  request(r: SliceRequest, prefetch: SliceRequest[] = []): void {
    const hit = peekSlice(r);
    this.prefetchQueue = prefetch;
    if (hit) {
      this.pending = null;
      this.deliver(hit, r);
      this.pump();
      return;
    }
    this.pending = r;
    this.pump();
  }

  private pump(): void {
    if (this.inflight || this.disposed) return;
    let next = this.pending;
    let isPrefetch = false;
    this.pending = null;
    if (!next) {
      while (this.prefetchQueue.length) {
        const cand = this.prefetchQueue.shift()!;
        if (!peekSlice(cand)) {
          next = cand;
          isPrefetch = true;
          break;
        }
      }
    }
    if (!next) return;
    const r = next;
    this.inflight = r;
    fetchSlice(r.path, r.axis, r.index, r.level)
      .then((s) => {
        if (!this.disposed && !isPrefetch) this.deliver(s, r);
      })
      .catch((e) => !this.disposed && !isPrefetch && this.onError(e))
      .finally(() => {
        this.inflight = null;
        this.pump();
      });
  }

  dispose(): void {
    this.disposed = true;
    this.pending = null;
    this.prefetchQueue = [];
  }
}
