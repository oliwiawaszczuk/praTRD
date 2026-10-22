import { describe, expect, it } from "vitest";
import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import { ijkToWorld, viewBasis, worldToIjk } from "./geometry.ts";

const ct: LevelGeometry = {
  size: [512, 512, 621],
  spacing: [0.39, 0.39, 0.45],
  origin: [-108.5, -235.5, -937.97],
  direction: [1, 0, 0, 0, 1, 0, 0, 0, 1],
};

describe("world ↔ ijk", () => {
  it("round-trips, also for a rotated direction", () => {
    const c = Math.cos(0.4);
    const s = Math.sin(0.4);
    const rot: LevelGeometry = { ...ct, direction: [c, 0, s, 0, 1, 0, -s, 0, c] };
    for (const g of [ct, rot]) {
      const w = ijkToWorld(g, [10.5, 200, 33]);
      const back = worldToIjk(g, w);
      back.forEach((v, n) => expect(v).toBeCloseTo([10.5, 200, 33][n], 9));
    }
  });
});

describe("viewBasis", () => {
  it("standard axial CT", () => {
    expect(viewBasis(ct, "axial")).toEqual({
      sliceAxis: 2, uAxis: 0, vAxis: 1, uFlip: false, vFlip: false, sliceSign: 1,
    });
    // coronal: rows are k (+S); screen-down is inferior → flipped
    expect(viewBasis(ct, "coronal")).toMatchObject({ sliceAxis: 1, uAxis: 0, vAxis: 2, vFlip: true });
    expect(viewBasis(ct, "sagittal")).toMatchObject({ sliceAxis: 0, uAxis: 1, vAxis: 2, vFlip: true });
  });

  it("left-right flipped volume (e.g. from NIfTI RAS)", () => {
    const flipped = { ...ct, direction: [-1, 0, 0, 0, -1, 0, 0, 0, 1] };
    expect(viewBasis(flipped, "axial")).toMatchObject({ uFlip: true, vFlip: true });
  });

  it("permuted axes: a sagittally acquired MR", () => {
    // i = +y (posterior), j = -z (inferior), k = +x (left): slices are sagittal
    const sag: LevelGeometry = { ...ct, direction: [0, 0, 1, 1, 0, 0, 0, -1, 0] };
    expect(viewBasis(sag, "sagittal")).toEqual({
      sliceAxis: 2, uAxis: 0, vAxis: 1, uFlip: false, vFlip: false, sliceSign: 1,
    });
    expect(viewBasis(sag, "axial")).toMatchObject({ sliceAxis: 1, uAxis: 2, vAxis: 0 });
  });
});
