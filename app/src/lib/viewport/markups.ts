// Markups (point, ruler, angle, ROI box) — world LPS mm, stored in a "pomiary/markupy"
// node's params. Measurements are computed here for instant feedback while dragging; the
// sidecar computes the same numbers for the graph (nodes/pomiary.py: markup_measure).

import { num } from "#lib/ui/format.ts";
import type { Vec3 } from "./geometry.ts";

export type MarkupType = "point" | "line" | "angle" | "roi";

export interface Markup {
  id: string;
  type: MarkupType;
  name: string;
  p: Vec3[];
}

export const MARKUP_POINTS: Record<MarkupType, number> = { point: 1, line: 2, angle: 3, roi: 2 };
export const MARKUP_LABEL: Record<MarkupType, string> = { point: "Punkt", line: "Linijka", angle: "Kąt", roi: "ROI" };
export const MARKUP_COLOR = "#f2994a"; // = --port-punkty

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const len = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);

/** Headline number: length (mm), angle (°) or ROI volume (ml); null for a point. */
export function measure(m: Markup): { value: number | null; unit: string } {
  const p = m.p;
  if (m.type === "line" && p.length === 2) return { value: len(sub(p[1], p[0])), unit: "mm" };
  if (m.type === "angle" && p.length === 3) {
    const a = sub(p[0], p[1]);
    const b = sub(p[2], p[1]);
    const na = len(a);
    const nb = len(b);
    if (!na || !nb) return { value: 0, unit: "°" };
    const c = Math.min(1, Math.max(-1, (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb)));
    return { value: (Math.acos(c) * 180) / Math.PI, unit: "°" };
  }
  if (m.type === "roi" && p.length === 2) {
    const d = sub(p[1], p[0]);
    return { value: Math.abs(d[0] * d[1] * d[2]) / 1000, unit: "ml" };
  }
  return { value: null, unit: "" };
}

/** Short label drawn next to a markup in the views. */
export function measureText(m: Markup): string {
  const { value, unit } = measure(m);
  if (value === null) return m.name;
  if (m.type === "roi") {
    const d = sub(m.p[1], m.p[0]).map((x) => num(Math.abs(x), 0));
    return `${d.join("×")} mm`;
  }
  return `${num(value, unit === "°" ? 1 : value < 10 ? 2 : 1)} ${unit}`;
}

export function roiBox(m: Markup): { lo: Vec3; hi: Vec3 } {
  const [a, b] = m.p;
  return {
    lo: [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.min(a[2], b[2])],
    hi: [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2])],
  };
}

export function centroid(m: Markup): Vec3 {
  const c: Vec3 = [0, 0, 0];
  for (const q of m.p) for (let n = 0; n < 3; n++) c[n] += q[n] / m.p.length;
  return c;
}

export function newMarkupId(): string {
  return Math.random().toString(36).slice(2, 10);
}

/** Next default name, e.g. "Linijka 3" — numbering per type, never reusing a visible name. */
export function defaultName(items: Markup[], type: MarkupType): string {
  const used = new Set(items.map((m) => m.name));
  for (let n = 1; ; n++) {
    const name = `${MARKUP_LABEL[type]} ${n}`;
    if (!used.has(name)) return name;
  }
}
