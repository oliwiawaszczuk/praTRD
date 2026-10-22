// Brush strokes (world-mm spheres) rasterised onto one slice of a label grid — the same
// voxel-centre test the sidecar's edit node uses, so the instant feedback matches the result.

import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import { SLICE_ROWS_COLS, worldToIjk } from "./geometry.ts";
import type { Stroke } from "./layers.ts";

export const EDIT_ADD = 1;
export const EDIT_ERASE = 2;

/**
 * Fill `out` (rows × cols, row-major like the slice endpoint's arrays) with EDIT_ADD /
 * EDIT_ERASE where the strokes cover slice `index` along `sliceAxis` of grid `g`; later
 * strokes win. Returns false when nothing touches the slice (out is then all zero).
 */
export function rasterizeStrokes(
  out: Uint8Array,
  g: LevelGeometry,
  sliceAxis: 0 | 1 | 2,
  index: number,
  strokes: Stroke[],
): boolean {
  out.fill(0);
  const [ra, ca] = SLICE_ROWS_COLS[sliceAxis];
  const rows = g.size[ra];
  const cols = g.size[ca];
  const sr = g.spacing[ra];
  const sc = g.spacing[ca];
  const ss = g.spacing[sliceAxis];
  let any = false;
  for (const st of strokes) {
    const v = st.mode === "erase" ? EDIT_ERASE : EDIT_ADD;
    for (const p of st.p) {
      const c = worldToIjk(g, p);
      const d = (c[sliceAxis] - index) * ss;
      const r2 = st.r * st.r - d * d;
      if (r2 < 0) continue;
      const rr = Math.sqrt(r2);
      const r0 = Math.max(0, Math.ceil(c[ra] - rr / sr));
      const r1 = Math.min(rows - 1, Math.floor(c[ra] + rr / sr));
      const c0 = Math.max(0, Math.ceil(c[ca] - rr / sc));
      const c1 = Math.min(cols - 1, Math.floor(c[ca] + rr / sc));
      for (let y = r0; y <= r1; y++) {
        const dy = (y - c[ra]) * sr;
        const left = r2 - dy * dy;
        if (left < 0) continue;
        const base = y * cols;
        for (let x = c0; x <= c1; x++) {
          const dx = (x - c[ca]) * sc;
          if (dx * dx <= left) {
            out[base + x] = v;
            any = true;
          }
        }
      }
    }
  }
  return any;
}
