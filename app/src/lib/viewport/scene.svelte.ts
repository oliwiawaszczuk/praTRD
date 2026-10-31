// Scene state shared by all viewports of the Scena tab: the cursor (one LPS point all views
// are synced to — global, so switching layers never moves the slices), window/level and 3-D
// transfer function per shown volume, layout. Persisted per workspace (wsGet/wsSet).

import { getSetting } from "#lib/core/appSettings.svelte.ts";
import type { VolumeEntry, VolumeMeta } from "#lib/core/library.svelte.ts";
import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
import { centerWorld, worldToIjk, type Plane, type Vec3 } from "./geometry.ts";
import { defaultTf, type TfPresetId, type WL } from "./presets.ts";

export type Layout = "quad" | "main3d" | "single";
export type ViewId = Plane | "3d";

interface VolumeViewState {
  wl: WL;
  tf: TfPresetId;
}

let cursor = $state<Vec3 | null>(wsGet<Vec3 | null>("scena_cursor", null));
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
let focusTick = $state(0); // F over the views: centre every view on the cursor
let meshOpacity = $state(wsGet<number>("scena_meshOpacity", 1));

export const scene = {
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
    return view ? cursor : null;
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
  get focusTick() {
    return focusTick;
  },
  get meshOpacity() {
    return meshOpacity;
  },
};

export function requestFocus(): void {
  focusTick++;
}

export function setMeshOpacity(o: number): void {
  meshOpacity = o;
  wsSet("scena_meshOpacity", o);
}

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
  if (key === viewKey && view) {
    // same node, other value range (its input was shown until the result came, e.g. CT under
    // a 0…1 vesselness map): the old window would paint it one flat grey — take the new one
    if (!windowFits(view.wl, m.stats)) {
      view.wl = { ...v.window };
      view.tf = defaultTf(v);
      persist();
    }
    return;
  }
  viewKey = key;
  const saved = wsGet<VolumeViewState | null>(`scena_view_${key}`, null);
  view = saved ? { wl: saved.wl, tf: saved.tf } : { wl: { ...v.window }, tf: defaultTf(v) };
  // the cursor stays at the same anatomical point; only a point outside the new volume
  // (another patient, a crop elsewhere) is moved to its centre
  if (!cursor || !inside(m, cursor)) {
    cursor = centerWorld(m.levels[0]);
    wsSet("scena_cursor", cursor);
  }
}

function inside(m: VolumeMeta, w: Vec3): boolean {
  const g = m.levels[0];
  const ijk = worldToIjk(g, w);
  return ijk.every((c, a) => c >= -0.5 && c <= g.size[a] - 0.5);
}

/** A window that shows something of a volume with these stats. */
function windowFits(wl: WL, st: VolumeMeta["stats"]): boolean {
  const range = Math.max(1e-9, st.max - st.min);
  return wl.width <= 20 * range && wl.center > st.min - wl.width && wl.center < st.max + wl.width;
}

export function setCursor(c: Vec3): void {
  if (!view) return;
  cursor = c;
  wsSet("scena_cursor", c);
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
