import { describe, expect, it } from "vitest";
import { contour, viewAffine } from "./meshcut.ts";

// unit cube [0,10]³, 12 triangles
const V = [0, 0, 0, 10, 0, 0, 10, 10, 0, 0, 10, 0, 0, 0, 10, 10, 0, 10, 10, 10, 10, 0, 10, 10];
const F = [
  [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
  [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
];
const cube = {
  verts: new Float32Array(V),
  cells: new Uint32Array(F.flatMap((f) => [3, ...f])),
  nVerts: 8,
  nFaces: 12,
};
// axial view: depth = z − slice, screen = (x, y) × 2 px/mm
const view = (z: number) => ({
  depth: (w: number[]) => w[2] - z,
  toScreen: (w: number[]): [number, number] => [2 * w[0], 2 * w[1]],
});

describe("mesh cut by a slice", () => {
  it("is the square outline at any height inside the cube", () => {
    const d = contour(cube, viewAffine(view(3.7)));
    const segs = d.split("M").filter(Boolean);
    expect(segs.length).toBe(8); // 4 side faces × 2 triangles
    const pts = segs.flatMap((s) => s.split("L").map((p) => p.trim().split(" ").map(Number)));
    for (const [x, y] of pts) {
      expect(x === 0 || x === 20 || y === 0 || y === 20).toBe(true);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(20);
    }
  });
  it("is empty outside the mesh and follows the slice without recomputing depths", () => {
    expect(contour(cube, viewAffine(view(12)))).toBe("");
    expect(contour(cube, viewAffine(view(-1)))).toBe("");
    expect(contour(cube, viewAffine(view(5))).split("M").length - 1).toBe(8);
  });
});
