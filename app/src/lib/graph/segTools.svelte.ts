// Segmentation tools used inside the 2-D views (seeds for region growing, brush/eraser for
// the edit node). A tool always belongs to one node; its results land in that node's params.

import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
import type { SegTool } from "#lib/viewport/layers.ts";
import { cancelDraft } from "#lib/viewport/markupDraft.svelte.ts";
import type { CutDepth, CutOp, CutShape } from "#lib/viewport/cuts.ts";

let tool = $state<SegTool | null>(null);
let nodeId = $state<string | null>(null);
let brushR = $state(wsGet<number>("seg_brushR", 3));
let cut = $state(
  wsGet<{ shape: CutShape; op: CutOp; depth: CutDepth }>("seg_cut", { shape: "lasso", op: "erase", depth: "all" }),
);
let focusMarkup = $state<string | null>(null); // markup hovered in a node card → highlighted in views

export const segTools = {
  get tool() {
    return tool;
  },
  get nodeId() {
    return nodeId;
  },
  get brushR() {
    return brushR;
  },
  get cut() {
    return cut;
  },
  get focusMarkup() {
    return focusMarkup;
  },
};

export function setTool(t: SegTool | null, node: string | null = null): void {
  cancelDraft(); // an unfinished markup of the previous tool
  tool = t;
  nodeId = t ? node : null;
}

export function setBrushR(r: number): void {
  brushR = Math.min(50, Math.max(0.5, Math.round(r * 10) / 10));
  wsSet("seg_brushR", brushR);
}

export function setFocusMarkup(id: string | null): void {
  focusMarkup = id;
}

export function setCut(patch: Partial<{ shape: CutShape; op: CutOp; depth: CutDepth }>): void {
  cut = { ...cut, ...patch };
  wsSet("seg_cut", cut);
}
