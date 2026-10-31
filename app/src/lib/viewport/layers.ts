// What is drawn ON a 2-D view besides the background slice: a label overlay, a live
// threshold preview and the segmentation tools (seeds, brush). Passed down from the scene.

import type { VolumeMeta } from "#lib/core/library.svelte.ts";
import type { Vec3 } from "./geometry.ts";
import type { Markup, MarkupType } from "./markups.ts";
import type { Cut, CutDepth, CutOp, CutShape } from "./cuts.ts";

export interface OverlaySpec {
  ref: string; // label volume (segment / segmentacja result)
  meta: VolumeMeta;
  colors: Record<number, string>; // label → "#rrggbb"
  full?: boolean; // from a full-resolution run (not a preview)
  key?: string; // what is displayed ("node:<gid>:<nid>")
  strokes?: number; // edit node: strokes contained in this result
  node?: string; // graph node this label layer comes from
}

/** A surface shown in every view: shaded in 3-D, its cut with the slice plane in 2-D. */
export interface MeshSpec {
  ref: string;
  color: string;
  name: string;
}

export type SegTool = "seed" | "brush" | "erase" | "cut" | MarkupType;

export interface MarkupGroup {
  nodeId: string;
  items: Markup[];
}

/** A brush stroke (spheres along a path). */
export interface BrushStroke {
  kind?: undefined;
  p: Vec3[];
  r: number; // mm
  mode: "add" | "erase";
}

/** Anything the edit node replays in order: brush strokes and scissors cuts. */
export type Stroke = BrushStroke | Cut;

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
  /** the editable overlay (active / topmost segment layer) */
  overlay: OverlaySpec | null;
  /** the other visible segment layers, bottom → top — shown together with `overlay` */
  extras: OverlaySpec[];
  /** live threshold preview straight from background values (while a slider moves) */
  threshold: { lo: number; hi: number; color: string; node?: string } | null;
  alpha: number;
  outline: boolean;
  tool: SegTool | null;
  brushR: number;
  /** scissors settings (shape drawn, what happens inside, depth in 2-D) */
  cut: { shape: CutShape; op: CutOp; depth: CutDepth };
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
  /** surfaces (the displayed mesh node) */
  meshes: MeshSpec[];
  /** 3-D surface opacity (0..1) */
  meshOpacity: number;
  onSeed?: (w: Vec3) => void;
  onStroke?: (s: Stroke) => void;
  onMarkups?: (nodeId: string, items: Markup[]) => void;
}

export const NO_LAYERS: SliceLayers = {
  overlay: null,
  extras: [],
  threshold: null,
  alpha: 0.45,
  outline: true,
  tool: null,
  brushR: 3,
  cut: { shape: "lasso", op: "erase", depth: "all" },
  pending: [],
  seeds: [],
  color: "#7bc47f",
  toolNode: null,
  markups: [],
  focusMarkup: null,
  meshes: [],
  meshOpacity: 1,
};

export function hexRgb(hex: string): [number, number, number] {
  const v = parseInt(hex.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}
