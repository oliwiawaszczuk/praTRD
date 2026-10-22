// Scene state shared by all viewports of the Scena tab: which volume is shown, the
// cursor (one LPS point all views are synced to), window/level, 3-D transfer function,
// layout. Per-volume parts are persisted per workspace (wsGet/wsSet).

import { getSetting } from "#lib/core/appSettings.svelte.ts";
import type { VolumeEntry, VolumeMeta } from "#lib/core/library.svelte.ts";
import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
import { centerWorld, type Plane, type Vec3 } from "./geometry.ts";
import { defaultTf, type TfPresetId, type WL } from "./presets.ts";

export type Layout = "quad" | "main3d" | "single";
export type ViewId = Plane | "3d";

interface VolumeViewState {
  cursor: Vec3;
  wl: WL;
  tf: TfPresetId;
}

let volumeId = $state(wsGet<string>("scena_volume", ""));
// What the per-view state (cursor, W/L, 3-D preset) is keyed by: "lib:<vid>" or
// "node:<gid>:<nid>" — a node keeps its view state while its result ref changes.
let viewKey = $state("");
let layout = $state<Layout>(wsGet<Layout>("scena_layout", "quad"));
let maximized = $state<ViewId | null>(wsGet<ViewId | null>("scena_maximized", null));
let single = $state<ViewId>(wsGet<ViewId>("scena_single", "axial"));
let view = $state<VolumeViewState | null>(null);
let meta = $state.raw<VolumeMeta | null>(null);
let overlayAlpha = $state(wsGet<number>("scena_ovAlpha", 0.45));
let overlayOutline = $state(wsGet<boolean>("scena_ovOutline", true));

export const scene = {
  get volumeId() {
    return volumeId;
  },
  get layout() {
    return layout;
  },
  get maximized() {
    return maximized;
  },
  get single() {
    return single;
  },
  get cursor(): Vec3 | null {
    return view?.cursor ?? null;
  },
  get wl(): WL | null {
    return view?.wl ?? null;
  },
  get tf(): TfPresetId | null {
    return view?.tf ?? null;
  },
  get meta() {
    return meta;
  },
  get viewKey() {
    return viewKey;
  },
  get overlayAlpha() {
    return overlayAlpha;
  },
  get overlayOutline() {
    return overlayOutline;
  },
};

export function setOverlayStyle(alpha: number, outline: boolean): void {
  overlayAlpha = alpha;
  overlayOutline = outline;
  wsSet("scena_ovAlpha", alpha);
  wsSet("scena_ovOutline", outline);
}

function persist(): void {
  if (viewKey && view) wsSet(`scena_view_${viewKey}`, $state.snapshot(view));
}

/** Show a volume. `key` identifies what is displayed (library volume or graph node); the
 * view state survives a change of the underlying volume as long as the key is the same. */
export function bindVolume(v: VolumeEntry, m: VolumeMeta, key: string): void {
  meta = m;
  if (key === viewKey && view) return;
  const prevCursor = view?.cursor ?? null;
  viewKey = key;
  const saved = wsGet<VolumeViewState | null>(`scena_view_${key}`, null);
  // a new key keeps the cursor at the same anatomical point (source → result and back)
  view = saved ?? { cursor: prevCursor ?? centerWorld(m.levels[0]), wl: { ...v.window }, tf: defaultTf(v) };
}

export function selectVolume(id: string): void {
  volumeId = id;
  wsSet("scena_volume", id);
}

export function setCursor(c: Vec3): void {
  if (!view) return;
  view.cursor = c;
  persist();
}

export function setWL(wl: WL): void {
  if (!view) return;
  view.wl = wl;
  persist();
}

export function setTf(tf: TfPresetId): void {
  if (!view) return;
  view.tf = tf;
  persist();
}

export function setLayout(l: Layout): void {
  layout = l;
  maximized = null;
  wsSet("scena_layout", l);
  wsSet("scena_maximized", null);
}

export function setSingle(v: ViewId): void {
  single = v;
  wsSet("scena_single", v);
}

export function toggleMaximized(v: ViewId): void {
  maximized = maximized === v ? null : v;
  wsSet("scena_maximized", maximized);
}

/** Largest level for the 3-D view within the GPU voxel budget (global setting). */
export function level3d(m: VolumeMeta): number {
  const budget = getSetting<number>("gpu3dVoxels", 256 * 1024 * 1024);
  for (let L = 0; L < m.levels.length; L++) {
    const s = m.levels[L].size;
    if (s[0] * s[1] * s[2] <= budget && Math.max(...s) <= 2048) return L;
  }
  return m.levels.length - 1;
}
