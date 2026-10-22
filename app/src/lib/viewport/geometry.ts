// Volume ↔ world (LPS mm) math and anatomical view orientation.
// Conventions (same as the sidecar): voxel arrays [k, j, i]; size/spacing/direction in
// (i, j, k) order; direction row-major 3×3 whose COLUMNS are the i, j, k axes in LPS;
// world = origin + D · (spacing ∘ ijk), origin = centre of voxel (0,0,0).

import type { LevelGeometry } from "#lib/core/library.svelte.ts";

export type Vec3 = [number, number, number];
export type Plane = "axial" | "coronal" | "sagittal";

export const PLANE_LABEL: Record<Plane, string> = {
  axial: "Osiowy",
  coronal: "Czołowy",
  sagittal: "Strzałkowy",
};

/** Slicer's colour convention (R/G/Y) — users of medical viewers expect it. */
export const PLANE_COLOR: Record<Plane, string> = {
  axial: "#e05a5a",
  coronal: "#6cbf6c",
  sagittal: "#e8c547",
};

const col = (d: number[], c: number): Vec3 => [d[c], d[3 + c], d[6 + c]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export function ijkToWorld(g: LevelGeometry, ijk: Vec3): Vec3 {
  const d = g.direction;
  const s: Vec3 = [ijk[0] * g.spacing[0], ijk[1] * g.spacing[1], ijk[2] * g.spacing[2]];
  return [
    g.origin[0] + d[0] * s[0] + d[1] * s[1] + d[2] * s[2],
    g.origin[1] + d[3] * s[0] + d[4] * s[1] + d[5] * s[2],
    g.origin[2] + d[6] * s[0] + d[7] * s[1] + d[8] * s[2],
  ];
}

/** Direction is orthonormal, so its inverse is its transpose. Continuous ijk. */
export function worldToIjk(g: LevelGeometry, w: Vec3): Vec3 {
  const d = g.direction;
  const r: Vec3 = [w[0] - g.origin[0], w[1] - g.origin[1], w[2] - g.origin[2]];
  return [
    (d[0] * r[0] + d[3] * r[1] + d[6] * r[2]) / g.spacing[0],
    (d[1] * r[0] + d[4] * r[1] + d[7] * r[2]) / g.spacing[1],
    (d[2] * r[0] + d[5] * r[1] + d[8] * r[2]) / g.spacing[2],
  ];
}

export function centerWorld(g: LevelGeometry): Vec3 {
  return ijkToWorld(g, [(g.size[0] - 1) / 2, (g.size[1] - 1) / 2, (g.size[2] - 1) / 2]);
}

// Desired screen axes in LPS (radiological convention):
//   axial:    right = patient Left (+x),     down = Posterior (+y)
//   coronal:  right = patient Left (+x),     down = Inferior (−z)
//   sagittal: right = Posterior (+y),        down = Inferior (−z)
const SCREEN: Record<Plane, { right: Vec3; down: Vec3; normal: Vec3 }> = {
  axial: { right: [1, 0, 0], down: [0, 1, 0], normal: [0, 0, 1] },
  coronal: { right: [1, 0, 0], down: [0, 0, -1], normal: [0, 1, 0] },
  sagittal: { right: [0, 1, 0], down: [0, 0, -1], normal: [1, 0, 0] },
};

/** How one anatomical view maps onto the volume's index axes. */
export interface ViewBasis {
  sliceAxis: 0 | 1 | 2; // index axis (i/j/k) the view scrolls through
  uAxis: 0 | 1 | 2; // index axis along screen-right
  vAxis: 0 | 1 | 2; // index axis along screen-down
  uFlip: boolean; // screen-right runs towards decreasing index
  vFlip: boolean;
  sliceSign: 1 | -1; // +1: increasing slice index moves along the plane normal
}

/** For axis-aligned volumes (any permutation / flips) this is exact; for oblique series
 * it picks the closest index plane (true oblique reslicing is a later feature). */
export function viewBasis(g: LevelGeometry, plane: Plane): ViewBasis {
  const axes = [0, 1, 2].map((c) => col(g.direction, c));
  const want = SCREEN[plane];
  const best = (v: Vec3, exclude: number[]) => {
    let pick = -1;
    let score = -1;
    for (let c = 0; c < 3; c++) {
      if (exclude.includes(c)) continue;
      const s = Math.abs(dot(axes[c], v));
      if (s > score) {
        score = s;
        pick = c;
      }
    }
    return pick as 0 | 1 | 2;
  };
  const sliceAxis = best(want.normal, []);
  const uAxis = best(want.right, [sliceAxis]);
  const vAxis = ([0, 1, 2].find((c) => c !== sliceAxis && c !== uAxis) ?? 0) as 0 | 1 | 2;
  return {
    sliceAxis,
    uAxis,
    vAxis,
    uFlip: dot(axes[uAxis], want.right) < 0,
    vFlip: dot(axes[vAxis], want.down) < 0,
    sliceSign: dot(axes[sliceAxis], want.normal) < 0 ? -1 : 1,
  };
}

/** Index axis "i/j/k" name used by the slice endpoint, and the [rows, cols] index axes of
 * the slice array it returns ("k" → [j, i], "j" → [k, i], "i" → [k, j]). */
export const AXIS_NAME = ["i", "j", "k"] as const;
export const SLICE_ROWS_COLS: Record<0 | 1 | 2, [0 | 1 | 2, 0 | 1 | 2]> = {
  2: [1, 0],
  1: [2, 0],
  0: [2, 1],
};

/** Orientation letters at the screen edges (left, right, top, bottom). */
export function edgeLetters(plane: Plane): [string, string, string, string] {
  if (plane === "axial") return ["R", "L", "A", "P"];
  if (plane === "coronal") return ["R", "L", "S", "I"];
  return ["A", "P", "S", "I"];
}
