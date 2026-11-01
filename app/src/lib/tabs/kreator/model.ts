// User node definition (mirrors src/pratrd/custom/manifest.py) + starting templates.
// Everything that ends up in code (ids, keys, slug, template code) is English; labels
// shown on the card stay Polish.

import type { ParamSchema, PortKind } from "#lib/graph/types.ts";

export interface PortDef {
  id: string;
  label: string;
  kind: PortKind;
  multi?: boolean;
  optional?: boolean;
}

export type ParamType = "number" | "int" | "bool" | "select";

export interface ParamDef {
  key: string;
  label: string;
  type: ParamType;
  default: unknown;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  unit?: string;
  options?: { value: string; label: string }[];
  help?: string;
}

export interface Manifest {
  slug: string;
  label: string;
  domain: string;
  description: string;
  inputs: PortDef[];
  outputs: PortDef[];
  params: ParamDef[];
  cost: "light" | "heavy";
}

export const KINDS: PortKind[] = ["wolumen", "segment", "segmentacja", "mesh", "tabela", "liczba", "punkty"];

/** Default code name of a new socket of this kind. */
export const KIND_ID: Record<PortKind, string> = {
  wolumen: "image",
  segment: "mask",
  segmentacja: "labels",
  mesh: "mesh",
  tabela: "table",
  liczba: "value",
  punkty: "points",
};

/** What `inputs.<id>` is in Python, and what run() may return for an output of that kind. */
export const KIND_IN: Record<PortKind, string> = {
  wolumen: "Volume: .array [k,j,i], .spacing (mm), .shape, .to_mm(), .to_ijk()",
  segment: "Volume (maska 0/1): .array, .spacing, .voxel_ml",
  segmentacja: "Volume (etykiety 0..N): .array, .labels",
  mesh: "Mesh: .verts [N,3] mm, .faces [M,3]",
  tabela: "dict: title, columns, rows",
  liczba: "float",
  punkty: "lista markupów: {type, name, p: [[x,y,z], …]}",
};
export const KIND_OUT: Record<PortKind, string> = {
  wolumen: "tablica numpy o kształcie wejścia (albo ctx.volume(...))",
  segment: "tablica bool / 0-1 o kształcie wejścia",
  segmentacja: "tablica całkowita 0..255 (ctx.volume(arr, labels=[...]))",
  mesh: "(verts [N,3] mm, faces [M,3])",
  tabela: "lista słowników [{kolumna: wartość}, …] (albo ctx.table(...))",
  liczba: "liczba",
  punkty: "lista [x, y, z] w mm",
};

const PY_KEYWORDS = new Set(
  "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield".split(" "),
);

export const validIdent = (s: string): boolean => /^[a-z_][a-z0-9_]{0,23}$/.test(s) && !PY_KEYWORDS.has(s);

/** `base` made unique among `taken` (mask, mask_2, …), within `max` characters. */
export function uniqueName(base: string, taken: Iterable<string>, max = 24): string {
  const used = new Set(taken);
  let out = base.slice(0, max);
  for (let n = 2; used.has(out); n++) out = `${base.slice(0, max - 3)}_${n}`;
  return out;
}

/** Schema for ParamField (the live preview on the card). */
export function paramSchema(p: ParamDef): ParamSchema {
  return {
    key: p.key,
    label: p.label,
    type: p.type,
    default: p.default,
    min: p.min ?? null,
    max: p.max ?? null,
    step: p.step ?? null,
    unit: p.unit ?? "",
    options: p.options ?? [],
    help: p.help ?? "",
    showIf: null,
  };
}

export function newParam(type: ParamType, taken: string[]): ParamDef {
  const [base, label] = (
    { number: ["value", "Wartość"], int: ["count", "Liczba"], bool: ["enabled", "Włącz"], select: ["mode", "Tryb"] } as const
  )[type];
  const key = uniqueName(base, taken);
  if (type === "number") return { key, label, type, default: 1, min: 0, max: 10, step: 0.1, unit: "" };
  if (type === "int") return { key, label, type, default: 1, min: 0, max: 10, step: 1, unit: "" };
  if (type === "bool") return { key, label, type, default: false };
  return {
    key,
    label,
    type,
    default: "a",
    options: [
      { value: "a", label: "A" },
      { value: "b", label: "B" },
    ],
  };
}

// ── code ─────────────────────────────────────────────────────────────────────

const PY_TYPE: Record<PortKind, string> = {
  wolumen: "Volume",
  segment: "Volume (0/1 mask)",
  segmentacja: "Volume (labels 0..N)",
  mesh: "Mesh",
  tabela: "dict",
  liczba: "float",
  punkty: "list of markups",
};
const PY_RETURN: Record<PortKind, string> = {
  wolumen: "ndarray shaped like an input",
  segment: "bool ndarray shaped like an input",
  segmentacja: "int ndarray 0..255",
  mesh: "(verts, faces)",
  tabela: "list of dicts",
  liczba: "number",
  punkty: "[[x, y, z], ...] mm",
};

/** Skeleton for the current sockets: one line per input/parameter, return shaped like the outputs. */
export function codeSkeleton(m: Manifest): string {
  const lines = ["import numpy as np", "", "", "def run(inputs, params, ctx):"];
  const body = [
    ...m.inputs.map((p) => `    ${p.id} = inputs.${p.id}  # ${p.multi ? `list of ${PY_TYPE[p.kind]}` : PY_TYPE[p.kind]}`),
    ...m.params.map((p) => `    ${p.key} = params.${p.key}${p.unit ? `  # [${p.unit}]` : ""}`),
  ];
  lines.push(...(body.length ? body : ["    # inputs.<id>, params.<key>"]));
  lines.push("");
  if (m.outputs.length === 1) {
    lines.push(`    return ...  # ${PY_RETURN[m.outputs[0].kind]}`);
  } else {
    lines.push("    return {");
    for (const o of m.outputs) lines.push(`        "${o.id}": ...,  # ${PY_RETURN[o.kind]}`);
    lines.push("    }");
  }
  lines.push("", "", "# optional, run by the Test button:", "# def test(result, inputs, params):", "#     assert ...", "");
  return lines.join("\n");
}

export interface Template {
  id: string;
  label: string;
  hint: string;
  ports: PortKind[][]; // [inputs, outputs] — drawn as a mini diagram on the tile
  manifest: Omit<Manifest, "slug">;
  slug: string; // base of the node id (made unique)
  code: string | null; // null → skeleton from the manifest
}

export const TEMPLATES: Template[] = [
  {
    id: "empty",
    label: "Pusty",
    hint: "Wolumen → wolumen",
    ports: [["wolumen"], ["wolumen"]],
    slug: "my_node",
    manifest: {
      label: "Mój node",
      domain: "wlasne",
      description: "",
      inputs: [{ id: "image", label: "Wolumen", kind: "wolumen" }],
      outputs: [{ id: "result", label: "Wynik", kind: "wolumen" }],
      params: [],
      cost: "light",
    },
    code: null,
  },
  {
    id: "threshold",
    label: "Próg",
    hint: "Maska z zakresu HU",
    ports: [["wolumen"], ["segment"]],
    slug: "threshold",
    manifest: {
      label: "Mój próg",
      domain: "segmentacja",
      description: "Segment: woksele z zakresu [od, do].",
      inputs: [{ id: "image", label: "Wolumen", kind: "wolumen" }],
      outputs: [{ id: "mask", label: "Maska", kind: "segment" }],
      params: [
        { key: "low", label: "Od", type: "number", default: 150, min: -1024, max: 3000, step: 1, unit: "HU" },
        { key: "high", label: "Do", type: "number", default: 600, min: -1024, max: 3000, step: 1, unit: "HU" },
      ],
      cost: "light",
    },
    code: `def run(inputs, params, ctx):
    a = inputs.image.array
    return (a >= params.low) & (a <= params.high)


def test(result, inputs, params):
    assert result["mask"].any(), "empty mask - check the range"
`,
  },
  {
    id: "gaussian",
    label: "Filtr",
    hint: "Gauss w mm (scipy)",
    ports: [["wolumen"], ["wolumen"]],
    slug: "gaussian",
    manifest: {
      label: "Mój Gauss",
      domain: "filtry",
      description: "Wygładzanie Gaussa; σ w milimetrach (uwzględnia spacing).",
      inputs: [{ id: "image", label: "Wolumen", kind: "wolumen" }],
      outputs: [{ id: "smoothed", label: "Wygładzony", kind: "wolumen" }],
      params: [{ key: "sigma", label: "σ", type: "number", default: 1.0, min: 0.1, max: 10, step: 0.1, unit: "mm" }],
      cost: "light",
    },
    code: `import numpy as np
from scipy import ndimage


def run(inputs, params, ctx):
    image = inputs.image
    sigma_vox = [params.sigma / s for s in image.spacing_kji]  # mm -> voxels, per axis
    out = ndimage.gaussian_filter(image.array.astype(np.float32), sigma_vox)
    return out.astype(image.array.dtype)  # same dtype = same display window as the input
`,
  },
  {
    id: "stats",
    label: "Statystyka",
    hint: "Wolumen + maska → tabela",
    ports: [["wolumen", "segment"], ["tabela", "liczba"]],
    slug: "mask_stats",
    manifest: {
      label: "Moja statystyka",
      domain: "pomiary",
      description: "Średnia, odchylenie i percentyle wewnątrz maski.",
      inputs: [
        { id: "image", label: "Wolumen", kind: "wolumen" },
        { id: "mask", label: "Maska", kind: "segment" },
      ],
      outputs: [
        { id: "table", label: "Tabela", kind: "tabela" },
        { id: "mean", label: "Średnia", kind: "liczba" },
      ],
      params: [],
      cost: "light",
    },
    code: `import numpy as np


def run(inputs, params, ctx):
    image, mask = inputs.image, inputs.mask
    if mask.shape != image.shape:
        raise ValueError("mask and volume must share the grid")
    values = image.array[mask.array > 0]
    mean = float(values.mean()) if values.size else 0.0
    p5, p50, p95 = np.percentile(values, [5, 50, 95]) if values.size else (0, 0, 0)
    rows = [
        {"measure": "Objętość", "value": values.size * mask.voxel_ml, "unit": "ml"},
        {"measure": "Średnia", "value": mean, "unit": ""},
        {"measure": "Odchylenie", "value": float(values.std()) if values.size else 0, "unit": ""},
        {"measure": "P5 / P50 / P95", "value": f"{p5:.1f} / {p50:.1f} / {p95:.1f}", "unit": ""},
    ]
    columns = [("measure", "Miara"), ("value", "Wartość"), ("unit", "Jedn.")]
    return {"table": ctx.table(rows, columns=columns), "mean": mean}
`,
  },
  {
    id: "surface",
    label: "Mesh",
    hint: "Segment → powierzchnia",
    ports: [["segment"], ["mesh"]],
    slug: "surface",
    manifest: {
      label: "Mój mesh",
      domain: "mesh",
      description: "Marching cubes (scikit-image) na masce, wierzchołki w mm.",
      inputs: [{ id: "mask", label: "Segment", kind: "segment" }],
      outputs: [{ id: "mesh", label: "Mesh", kind: "mesh" }],
      params: [],
      cost: "heavy",
    },
    code: `import numpy as np
from skimage.measure import marching_cubes


def run(inputs, params, ctx):
    mask = inputs.mask
    padded = np.pad(mask.array, 1)  # closed surface at the volume border
    kji, faces, _, _ = marching_cubes(padded, 0.5)
    ijk = kji[:, ::-1] - 1  # [k,j,i] -> (i,j,k), undo the padding
    verts = np.asarray(mask.origin) + (ijk * mask.spacing) @ mask.direction.T
    return verts, faces
`,
  },
];
