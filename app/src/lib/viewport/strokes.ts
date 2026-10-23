// Brush strokes (world-mm spheres) rasterised onto one slice of a label grid — the same
// voxel-centre test the sidecar's edit node uses, so the instant feedback matches the result.

import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import { SLICE_ROWS_COLS, worldToIjk } from "./geometry.ts";
import { cutInGrid, type Cut } from "./cuts.ts";
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
    if (st.kind === "cut") {
      any = cutSlice(out, g, sliceAxis, index, st) || any;
      continue;
    }
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

/** A scissors cut on one slice: texel (row, col) → q = q0 + row·qr + col·qc (additions only). */
function cutSlice(out: Uint8Array, g: LevelGeometry, sliceAxis: 0 | 1 | 2, index: number, cut: Cut): boolean {
  const [ra, ca] = SLICE_ROWS_COLS[sliceAxis];
  const rows = g.size[ra];
  const cols = g.size[ca];
  const { A, b, inside } = cutInGrid(cut, g, Math.min(...g.spacing) / 2);
  const col = (axis: number) => [A[0][axis], A[1][axis], A[2][axis], A[3][axis]];
  const qr = col(ra);
  const qc = col(ca);
  const q0 = [0, 1, 2, 3].map((n) => A[n][sliceAxis] * index + b[n]);
  const keep = cut.mode === "keep";
  const v = cut.mode === "add" ? EDIT_ADD : EDIT_ERASE;
  let any = keep;
  for (let r = 0; r < rows; r++) {
    let x = q0[0] + qr[0] * r;
    let y = q0[1] + qr[1] * r;
    let z = q0[2] + qr[2] * r;
    let w = q0[3] + qr[3] * r;
    const base = r * cols;
    for (let c = 0; c < cols; c++) {
      const hit = inside(x, y, z, w);
      if (keep) {
        if (!hit) out[base + c] = EDIT_ERASE;
      } else if (hit) {
        out[base + c] = v;
        any = true;
      }
      x += qc[0];
      y += qc[1];
      z += qc[2];
      w += qc[3];
    }
  }
  return any;
}
