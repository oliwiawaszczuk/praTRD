// Scissors (Slicer's "Scissors" effect): a shape drawn in a view, extruded along the view
// direction. Stored as a projection M (world → x, y, z, w; row-major 4×4) + a polygon in
// x/w, y/w — affine for a 2-D view (mm on the slice plane), perspective for the 3-D view.
// The sidecar applies the same definition (nodes/segmentacja.py: _cut).

import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import type { Vec3 } from "./geometry.ts";

export type CutShape = "lasso" | "rect" | "ellipse";
export type CutOp = "add" | "erase" | "keep";
export type CutDepth = "slice" | "all";

export interface Cut {
  kind: "cut";
  mode: CutOp;
  M: number[]; // 16, row-major
  poly: [number, number][];
  z: [number, number] | null; // range of z/w, null = unlimited depth
}

/** The polygon of a drawn shape (screen px): lasso as drawn, rect / ellipse from the drag. */
export function shapePolygon(shape: CutShape, pts: [number, number][]): [number, number][] {
  if (shape === "lasso" || pts.length < 2) return pts;
  const [a, b] = [pts[0], pts[pts.length - 1]];
  if (shape === "rect") return [a, [b[0], a[1]], b, [a[0], b[1]]];
  const cx = (a[0] + b[0]) / 2;
  const cy = (a[1] + b[1]) / 2;
  const rx = Math.abs(b[0] - a[0]) / 2;
  const ry = Math.abs(b[1] - a[1]) / 2;
  return Array.from({ length: 64 }, (_, n) => {
    const t = (n / 64) * Math.PI * 2;
    return [cx + rx * Math.cos(t), cy + ry * Math.sin(t)] as [number, number];
  });
}

export function polyArea(poly: [number, number][]): number {
  let a = 0;
  for (let n = 0; n < poly.length; n++) {
    const p = poly[n];
    const q = poly[(n + 1) % poly.length];
    a += p[0] * q[1] - q[0] * p[1];
  }
  return Math.abs(a) / 2;
}

export interface PolyRaster {
  grid: Uint8Array;
  nx: number;
  ny: number;
  lo: [number, number];
  inv: number; // 1 / cell size
}

/** Even-odd scanline fill of the polygon on a grid of its own plane (≤ maxCells per side). */
export function polyRaster(poly: [number, number][], cell = 0, maxCells = 1024): PolyRaster {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  const res = Math.max(cell, Math.max(x1 - x0, y1 - y0, 1e-9) / (maxCells - 1));
  const nx = Math.ceil((x1 - x0) / res) + 1;
  const ny = Math.ceil((y1 - y0) / res) + 1;
  const grid = new Uint8Array(nx * ny);
  const xs: number[] = [];
  for (let r = 0; r < ny; r++) {
    const y = y0 + r * res;
    xs.length = 0;
    for (let n = 0; n < poly.length; n++) {
      const [ax, ay] = poly[n];
      const [bx, by] = poly[(n + 1) % poly.length];
      if (ay <= y !== by <= y) xs.push(ax + ((y - ay) / (by - ay)) * (bx - ax));
    }
    xs.sort((a, b) => a - b);
    for (let n = 0; n + 1 < xs.length; n += 2) {
      const c0 = Math.max(0, Math.ceil((xs[n] - x0) / res));
      const c1 = Math.min(nx - 1, Math.floor((xs[n + 1] - x0) / res));
      grid.fill(1, r * nx + c0, r * nx + c1 + 1);
    }
  }
  return { grid, nx, ny, lo: [x0, y0], inv: 1 / res };
}

// a pending cut is rasterised on every redraw of every view — fill its polygon once
const RASTERS = new WeakMap<object, Map<number, PolyRaster>>();
function rasterOf(poly: [number, number][], cell: number): PolyRaster {
  let m = RASTERS.get(poly);
  if (!m) RASTERS.set(poly, (m = new Map()));
  let r = m.get(cell);
  if (!r) m.set(cell, (r = polyRaster(poly, cell)));
  return r;
}

/**
 * The cut in INDEX space of a grid: q(ijk) = A·ijk + b (4-vectors), so walking voxels is
 * additions only. Returns a tester for (x, y, z, w) = q.
 */
export function cutInGrid(cut: Cut, g: LevelGeometry, cell = 0) {
  const M = cut.M;
  const d = g.direction;
  const A: number[][] = [[], [], [], []];
  const b: number[] = [];
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 3; c++) {
      // (M[:, :3] · D)[r][c] · spacing[c]
      A[r][c] = (M[r * 4] * d[c] + M[r * 4 + 1] * d[3 + c] + M[r * 4 + 2] * d[6 + c]) * g.spacing[c];
    }
    b[r] = M[r * 4] * g.origin[0] + M[r * 4 + 1] * g.origin[1] + M[r * 4 + 2] * g.origin[2] + M[r * 4 + 3];
  }
  const ras = rasterOf(cut.poly, cell);
  const { grid, nx, ny, lo, inv } = ras;
  const z = cut.z;
  const inside = (x: number, y: number, zz: number, w: number): boolean => {
    if (w <= 1e-9) return false;
    const xi = Math.round((x / w - lo[0]) * inv);
    const yi = Math.round((y / w - lo[1]) * inv);
    if (xi < 0 || yi < 0 || xi >= nx || yi >= ny || !grid[yi * nx + xi]) return false;
    return !z || (zz / w >= z[0] && zz / w <= z[1]);
  };
  return { A, b, inside };
}

/** Affine cut frame of a 2-D view: x, y = mm along screen right / down, z = mm along the
 * normal, all from `o` (a point on the shown slice). */
export function planeMatrix(o: Vec3, eu: Vec3, ev: Vec3, en: Vec3): number[] {
  const row = (e: Vec3) => [e[0], e[1], e[2], -(e[0] * o[0] + e[1] * o[1] + e[2] * o[2])];
  return [...row(eu), ...row(ev), ...row(en), 0, 0, 0, 1];
}
