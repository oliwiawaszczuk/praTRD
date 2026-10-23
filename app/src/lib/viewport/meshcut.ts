// A mesh cut by a 2-D view's slice plane. The slice depth and the screen position are both
// affine in the world, so they are read off the view's projection once (4 points); every
// triangle is then tested with plain arithmetic. Per-vertex depths are cached per plane
// orientation — scrolling to the next slice only shifts them by a constant, so ~1.5 M
// triangles take a few ms and nothing is allocated per vertex.

import type { MeshData } from "#lib/core/meshes.svelte.ts";
import type { Vec3 } from "./geometry.ts";
import type { ViewProj } from "./layers.ts";

export interface Affine {
  d0: number;
  dn: Vec3;
  s0: [number, number];
  sx: Vec3;
  sy: Vec3;
}
/** depth(w) = d0 + dn·w and screen(w) = s0 + [sx·w, sy·w], read off a view's projection. */
export function viewAffine(p: Pick<ViewProj, "depth" | "toScreen">): Affine {
  const o: Vec3 = [0, 0, 0];
  const d0 = p.depth(o);
  const s0 = p.toScreen(o);
  const dn: Vec3 = [0, 0, 0];
  const sx: Vec3 = [0, 0, 0];
  const sy: Vec3 = [0, 0, 0];
  for (let n = 0; n < 3; n++) {
    const e: Vec3 = [0, 0, 0];
    e[n] = 100;
    dn[n] = (p.depth(e) - d0) / 100;
    const s = p.toScreen(e);
    sx[n] = (s[0] - s0[0]) / 100;
    sy[n] = (s[1] - s0[1]) / 100;
  }
  return { d0, dn, s0, sx, sy };
}

// per mesh: vertex depths along the current plane normal (recomputed only when it turns)
const depthCache = new WeakMap<object, { dn: Vec3; d: Float32Array }>();
function vertexDepths(m: Pick<MeshData, "verts" | "nVerts">, dn: Vec3): Float32Array {
  const hit = depthCache.get(m);
  if (hit && Math.abs(hit.dn[0] - dn[0]) + Math.abs(hit.dn[1] - dn[1]) + Math.abs(hit.dn[2] - dn[2]) < 1e-9) return hit.d;
  const v = m.verts;
  const d = new Float32Array(m.nVerts);
  for (let i = 0, j = 0; i < m.nVerts; i++, j += 3) d[i] = dn[0] * v[j] + dn[1] * v[j + 1] + dn[2] * v[j + 2];
  depthCache.set(m, { dn: [...dn], d });
  return d;
}

/** SVG path (M…L… per crossed triangle) of the mesh's cut with the plane depth = 0. */
export function contour(m: Pick<MeshData, "verts" | "cells" | "nVerts" | "nFaces">, a: Affine): string {
  const d = vertexDepths(m, a.dn);
  const off = a.d0;
  const v = m.verts;
  const c = m.cells;
  const parts: string[] = [];
  const pt = (i: number, j: number) => {
    // where edge i–j crosses depth 0 → screen px
    const di = d[i] + off;
    const t = di / (di - (d[j] + off));
    const x = v[3 * i] + t * (v[3 * j] - v[3 * i]);
    const y = v[3 * i + 1] + t * (v[3 * j + 1] - v[3 * i + 1]);
    const z = v[3 * i + 2] + t * (v[3 * j + 2] - v[3 * i + 2]);
    return `${(a.s0[0] + a.sx[0] * x + a.sx[1] * y + a.sx[2] * z).toFixed(1)} ${(a.s0[1] + a.sy[0] * x + a.sy[1] * y + a.sy[2] * z).toFixed(1)}`;
  };
  for (let f = 0; f < m.nFaces; f++) {
    const i0 = c[4 * f + 1];
    const i1 = c[4 * f + 2];
    const i2 = c[4 * f + 3];
    const a0 = d[i0] + off > 0;
    const a1 = d[i1] + off > 0;
    const a2 = d[i2] + off > 0;
    if (a0 === a1 && a1 === a2) continue;
    // the lone vertex on one side, the two edges leaving it cross the plane
    if (a0 === a1) parts.push(`M${pt(i2, i0)}L${pt(i2, i1)}`);
    else if (a0 === a2) parts.push(`M${pt(i1, i0)}L${pt(i1, i2)}`);
    else parts.push(`M${pt(i0, i1)}L${pt(i0, i2)}`);
  }
  return parts.join("");
}

