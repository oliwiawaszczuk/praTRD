import { describe, expect, it } from "vitest";
import { windowToRgba, type Slice } from "./slices.ts";

const grey = (px: number) => px & 0xff;

describe("windowToRgba", () => {
  const values = [-1024, -100, 0, 40, 80, 3071];
  const s: Slice = { rows: 1, cols: values.length, data: Int16Array.from(values) };

  it("maps the window linearly and clamps outside it", () => {
    const out = new Uint32Array(values.length);
    windowToRgba(s, 40, 80, out, { min: -1024, max: 3071 });
    expect(Array.from(out, grey)).toEqual([0, 0, 0, 127, 255, 255]);
    for (const px of out) expect(px >>> 24).toBe(0xff); // opaque
  });

  it("LUT path equals the float path", () => {
    const lut = new Uint32Array(values.length);
    const flt = new Uint32Array(values.length);
    windowToRgba(s, 300, 600, lut, { min: -1024, max: 3071 });
    const f: Slice = { ...s, data: Float32Array.from(values) };
    windowToRgba(f, 300, 600, flt, { min: -1024, max: 3071 });
    expect(Array.from(lut)).toEqual(Array.from(flt));
  });

  it("values outside the declared range are clamped, not read out of bounds", () => {
    const out = new Uint32Array(2);
    const odd: Slice = { rows: 1, cols: 2, data: Int16Array.from([-5000, 5000]) };
    windowToRgba(odd, 0, 100, out, { min: -1024, max: 3071 });
    expect(Array.from(out, grey)).toEqual([0, 255]);
  });
});
