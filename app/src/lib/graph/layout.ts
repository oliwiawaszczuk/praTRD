// Deterministic node geometry: port positions are computed, never measured from the DOM,
// so edges can be drawn for any number of nodes without layout reads.

import type { GNode, NodeTypeSchema } from "./types.ts";

export const NODE_W = 230;
export const HEADER_H = 30;
export const ROW_H = 24;
export const PARAM_H = 30;
export const THUMB_H = 96;
export const PORT_R = 6;

export function portRows(t: NodeTypeSchema): number {
  return Math.max(t.inputs.length, t.outputs.length);
}

export function inputPos(n: GNode, t: NodeTypeSchema, socket: string): [number, number] {
  const i = Math.max(0, t.inputs.findIndex((p) => p.id === socket));
  return [n.x, n.y + HEADER_H + i * ROW_H + ROW_H / 2];
}

export function outputPos(n: GNode, t: NodeTypeSchema, socket: string): [number, number] {
  const i = Math.max(0, t.outputs.findIndex((p) => p.id === socket));
  return [n.x + NODE_W, n.y + HEADER_H + i * ROW_H + ROW_H / 2];
}

/** Approximate height (marquee / fit-to-view only — the card itself may differ slightly). */
export function nodeHeight(t: NodeTypeSchema): number {
  const thumb = t.outputs.some((o) => ["wolumen", "segment", "segmentacja", "mesh"].includes(o.kind)) ? THUMB_H : 0;
  const params = t.widget === "cropbox" ? 96 : t.widget ? 80 + t.params.length * 12 : t.params.length * PARAM_H;
  const chart = t.outputs.some((o) => o.kind === "tabela") && t.widget !== "markups" ? 78 : 0;
  return HEADER_H + portRows(t) * ROW_H + params + thumb + chart + 12;
}

/** Cubic edge from an output (right) to an input (left), Blender-like. */
export function edgePath(a: [number, number], b: [number, number]): string {
  const dx = Math.max(40, Math.abs(b[0] - a[0]) * 0.5);
  return `M${a[0]},${a[1]} C${a[0] + dx},${a[1]} ${b[0] - dx},${b[1]} ${b[0]},${b[1]}`;
}
