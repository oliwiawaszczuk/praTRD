// Markups being placed or dragged right now — shared by all views, so a point moved in the
// axial view moves live in the others (and in 3-D) too. Committed to the node only at the end
// of the gesture (one undo step, one graph evaluation).

import type { Vec3 } from "./geometry.ts";
import { defaultName, MARKUP_POINTS, newMarkupId, type Markup, type MarkupType } from "./markups.ts";

interface Draft {
  nodeId: string;
  m: Markup;
  placed: number; // fixed points; the rest follow the pointer
}

let draft = $state<Draft | null>(null);
let live = $state<{ nodeId: string; m: Markup } | null>(null);

export const markupDraft = {
  get draft() {
    return draft;
  },
  /** a committed markup being dragged (overrides the stored one while the gesture lasts) */
  get live() {
    return live;
  },
};

/**
 * A click with a placing tool. Returns the node's new item list when the markup is complete
 * (point: 1 click, ruler: 2, angle: 3), else null and the draft waits for the next click.
 */
export function draftClick(nodeId: string, type: MarkupType, w: Vec3, items: Markup[]): Markup[] | null {
  const need = MARKUP_POINTS[type];
  if (!draft || draft.nodeId !== nodeId || draft.m.type !== type) {
    draft = {
      nodeId,
      m: { id: newMarkupId(), type, name: defaultName(items, type), p: Array.from({ length: need }, () => [...w] as Vec3) },
      placed: 1,
    };
  } else {
    draft.m.p[draft.placed] = [...w] as Vec3;
    draft.placed++;
  }
  if (draft.placed < need) return null;
  const done = $state.snapshot(draft.m) as Markup;
  draft = null;
  return [...items, done];
}

/** Pointer moved while placing: the unplaced points follow it (rubber band). */
export function draftHover(w: Vec3): void {
  if (!draft) return;
  for (let n = draft.placed; n < draft.m.p.length; n++) draft.m.p[n] = [...w] as Vec3;
}

/** ROI box from a drag: corners a, b (world), finished on release. */
export function draftBox(nodeId: string, a: Vec3, b: Vec3, items: Markup[]): void {
  if (!draft || draft.nodeId !== nodeId || draft.m.type !== "roi")
    draft = { nodeId, m: { id: newMarkupId(), type: "roi", name: defaultName(items, "roi"), p: [a, b] }, placed: 1 };
  else draft.m.p = [a, b];
}

export function finishBox(items: Markup[]): Markup[] | null {
  if (!draft || draft.m.type !== "roi") return null;
  const done = $state.snapshot(draft.m) as Markup;
  draft = null;
  return [...items, done];
}

export function cancelDraft(): void {
  draft = null;
}

export function setLive(nodeId: string, m: Markup | null): void {
  live = m ? { nodeId, m } : null;
}

/** Items of a node as currently seen: the dragged markup replaced, the draft appended. */
export function shownItems(nodeId: string, items: Markup[]): { m: Markup; draft: boolean }[] {
  const out = items.map((m) => ({ m: live?.nodeId === nodeId && live.m.id === m.id ? live.m : m, draft: false }));
  if (draft?.nodeId === nodeId) out.push({ m: draft.m, draft: true });
  return out;
}
