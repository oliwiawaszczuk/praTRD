// What is drawn ON a 2-D view besides the background slice: a label overlay, a live
// threshold preview and the segmentation tools (seeds, brush). Passed down from the scene.

import type { VolumeMeta } from "#lib/core/library.svelte.ts";
import type { Vec3 } from "./geometry.ts";
import type { Markup, MarkupType } from "./markups.ts";

export interface OverlaySpec {
  ref: string; // label volume (segment / segmentacja result)
  meta: VolumeMeta;
  colors: Record<number, string>; // label → "#rrggbb"
  full?: boolean; // from a full-resolution run (not a preview)
  key?: string; // what is displayed ("node:<gid>:<nid>")
  strokes?: number; // edit node: strokes contained in this result
}

export type SegTool = "seed" | "brush" | "erase" | MarkupType;

export interface MarkupGroup {
  nodeId: string;
  items: Markup[];
}

export interface Stroke {
  p: Vec3[];
  r: number; // mm
  mode: "add" | "erase";
}

/** How a 2-D view maps the world (handed to its overlay layers). */
export interface ViewProj {
  W: number;
  H: number;
  toScreen(w: Vec3): [number, number];
  /** signed distance (mm) from the shown slice plane */
  depth(w: Vec3): number;
  /** world point on the shown slice under CSS px (x, y) */
  worldAt(x: number, y: number): Vec3;
  /** |depth| ≤ tol → lies on this slice */
  tol: number;
  /** world axis (0 = x, 1 = y, 2 = z) along screen right, screen down, and the normal */
  axes: [number, number, number];
}

export interface SliceLayers {
  overlay: OverlaySpec | null;
  /** live threshold preview straight from background values (while a slider moves) */
  threshold: { lo: number; hi: number; color: string } | null;
  alpha: number;
  outline: boolean;
  tool: SegTool | null;
  brushR: number;
  /** committed strokes not yet in the shown result (drawn as instant feedback) */
  pending: Stroke[];
  seeds: Vec3[];
  color: string; // colour of the edited / grown segment (tool feedback)
  /** node the active tool belongs to (seeds / strokes / markups land in its params) */
  toolNode: string | null;
  /** markups of every Markupy node of the graph — always visible */
  markups: MarkupGroup[];
  /** highlighted markup (hovered in the node card) */
  focusMarkup: string | null;
  onSeed?: (w: Vec3) => void;
  onStroke?: (s: Stroke) => void;
  onMarkups?: (nodeId: string, items: Markup[]) => void;
}

export const NO_LAYERS: SliceLayers = {
  overlay: null,
  threshold: null,
  alpha: 0.45,
  outline: true,
  tool: null,
  brushR: 3,
  pending: [],
  seeds: [],
  color: "#7bc47f",
  toolNode: null,
  markups: [],
  focusMarkup: null,
};

export function hexRgb(hex: string): [number, number, number] {
  const v = parseInt(hex.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}
