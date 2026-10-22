import { describe, expect, it } from "vitest";
import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import { EDIT_ADD, EDIT_ERASE, rasterizeStrokes } from "./strokes.ts";

// 20 × 10 × 8 voxels (i, j, k), 0.5 × 0.5 × 2 mm, identity direction, origin 0
const g = { size: [20, 10, 8], spacing: [0.5, 0.5, 2], origin: [0, 0, 0], direction: [1, 0, 0, 0, 1, 0, 0, 0, 1] } as unknown as LevelGeometry;

describe("rasterizeStrokes", () => {
  it("draws the in-slice disk of a sphere (axial, rows = j, cols = i)", () => {
    const out = new Uint8Array(10 * 20);
    // centre i=10, j=5 on slice k=3 (z = 6 mm), r = 1 mm → radius 2 voxels in-plane
    expect(rasterizeStrokes(out, g, 2, 3, [{ p: [[5, 2.5, 6]], r: 1, mode: "add" }])).toBe(true);
    expect(out[5 * 20 + 10]).toBe(EDIT_ADD);
    expect(out[5 * 20 + 12]).toBe(EDIT_ADD); // 1 mm away: on the boundary
    expect(out[5 * 20 + 13]).toBe(0);
    expect(out.reduce((a, b) => a + (b ? 1 : 0), 0)).toBe(13); // |dx|²+|dy|² ≤ 4 lattice points
  });

  it("misses slices farther than r and lets later strokes win", () => {
    const out = new Uint8Array(10 * 20);
    expect(rasterizeStrokes(out, g, 2, 5, [{ p: [[5, 2.5, 6]], r: 1, mode: "add" }])).toBe(false); // 4 mm away
    rasterizeStrokes(out, g, 2, 3, [
      { p: [[5, 2.5, 6]], r: 1, mode: "add" },
      { p: [[5, 2.5, 6]], r: 0.5, mode: "erase" },
    ]);
    expect(out[5 * 20 + 10]).toBe(EDIT_ERASE);
    expect(out[5 * 20 + 12]).toBe(EDIT_ADD);
  });

  it("uses the slice array layout of other axes (sagittal: rows = k, cols = j)", () => {
    const out = new Uint8Array(8 * 10);
    rasterizeStrokes(out, g, 0, 10, [{ p: [[5, 2.5, 6]], r: 1, mode: "erase" }]);
    expect(out[3 * 10 + 5]).toBe(EDIT_ERASE);
  });
});
