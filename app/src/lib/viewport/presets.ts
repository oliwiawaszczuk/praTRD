// Window/level and 3-D transfer-function presets.

import type { VolumeEntry } from "#lib/core/library.svelte.ts";

export interface WL {
  center: number;
  width: number;
}

export const CT_WINDOWS: { name: string; center: number; width: number }[] = [
  { name: "Mózg", center: 40, width: 80 },
  { name: "Tkanki miękkie", center: 40, width: 400 },
  { name: "Angio", center: 300, width: 600 },
  { name: "Kości", center: 400, width: 1800 },
  { name: "Płuca", center: -600, width: 1500 },
];

export const autoWindow = (v: VolumeEntry): WL => ({
  center: (v.stats.p1 + v.stats.p99) / 2,
  width: Math.max(1, v.stats.p99 - v.stats.p1),
});

/** Piecewise-linear transfer function: points (value, opacity) and (value, r, g, b). */
export interface TransferFunction {
  opacity: [number, number][];
  color: [number, number, number, number][];
  shade: boolean;
  mip?: boolean;
}

export type TfPresetId = "ct-bone" | "ct-angio" | "ct-soft" | "mip" | "generic";

export const TF_LABELS: Record<TfPresetId, string> = {
  "ct-angio": "CT — naczynia (angio)",
  "ct-bone": "CT — kości",
  "ct-soft": "CT — skóra / tkanki miękkie",
  mip: "MIP (maks. intensywność)",
  generic: "Ogólny (wg histogramu)",
};

/** Calibrated in Hounsfield units: a CT, or any volume whose range looks like one. */
export const isHU = (v: VolumeEntry): boolean => v.modality === "CT" || (v.stats.min <= -500 && v.stats.max >= 300);

// every preset is always offered: on data that is not in HU (MR, NIfTI without a modality, a
// filtered map) the CT presets are stretched over the volume's own value range instead
export function tfPresetsFor(_v: VolumeEntry): TfPresetId[] {
  return ["generic", "ct-angio", "ct-bone", "ct-soft", "mip"];
}

export function defaultTf(v: VolumeEntry): TfPresetId {
  return isHU(v) ? "ct-angio" : "generic";
}

const HU_LO = -1024;
const HU_HI = 1500;

/** Map a HU preset onto the volume's own range (p1…p99 ↔ −1024…1500 HU). */
function stretch(tf: TransferFunction, v: VolumeEntry): TransferFunction {
  const lo = v.stats.p1;
  const span = Math.max(1e-9, v.stats.p99 - v.stats.p1);
  const map = (x: number) => lo + ((Math.min(x, HU_HI) - HU_LO) / (HU_HI - HU_LO)) * span;
  const top = (x: number) => (x >= 3000 ? v.stats.max : map(x));
  return {
    ...tf,
    opacity: tf.opacity.map(([x, o]) => [x <= HU_LO ? v.stats.min : top(x), o]),
    color: tf.color.map(([x, r, g, b]) => [top(x), r, g, b]),
  };
}

/** Values in HU for CT presets; the generic one follows the volume's percentiles. */
export function buildTf(id: TfPresetId, v: VolumeEntry, wl: WL): TransferFunction {
  const tf = buildHuTf(id, v, wl);
  return id.startsWith("ct-") && !isHU(v) ? stretch(tf, v) : tf;
}

function buildHuTf(id: TfPresetId, v: VolumeEntry, wl: WL): TransferFunction {
  switch (id) {
    case "ct-bone":
      return {
        shade: true,
        opacity: [[-1024, 0], [150, 0], [300, 0.15], [700, 0.6], [1500, 0.85], [3071, 0.9]],
        color: [[150, 0.55, 0.25, 0.15], [300, 0.88, 0.75, 0.6], [700, 0.97, 0.93, 0.85], [3071, 1, 1, 1]],
      };
    case "ct-angio":
      return {
        shade: true,
        opacity: [[-1024, 0], [130, 0], [200, 0.25], [400, 0.55], [800, 0.75], [3071, 0.85]],
        color: [[130, 0.55, 0.06, 0.05], [250, 0.9, 0.25, 0.18], [450, 1, 0.65, 0.5], [900, 1, 0.95, 0.9], [3071, 1, 1, 1]],
      };
    case "ct-soft":
      return {
        shade: true,
        opacity: [[-1024, 0], [-500, 0], [-300, 0.12], [-50, 0.18], [100, 0.3], [400, 0.7], [3071, 0.8]],
        color: [[-500, 0.55, 0.3, 0.2], [-100, 0.88, 0.6, 0.45], [100, 0.95, 0.75, 0.62], [400, 1, 0.95, 0.88], [3071, 1, 1, 1]],
      };
    case "mip": {
      const lo = wl.center - wl.width / 2;
      const hi = wl.center + wl.width / 2;
      return { shade: false, mip: true, opacity: [[lo, 0], [hi, 1]], color: [[lo, 0, 0, 0], [hi, 1, 1, 1]] };
    }
    default: {
      const lo = v.stats.p1;
      const hi = v.stats.p99;
      const a = lo + (hi - lo) * 0.3;
      return {
        shade: true,
        opacity: [[lo, 0], [a, 0], [hi, 0.6], [v.stats.max, 0.8]],
        color: [[a, 0.6, 0.3, 0.15], [hi, 1, 0.85, 0.65], [v.stats.max, 1, 1, 1]],
      };
    }
  }
}
