// Graph document + node-type schema (served by the sidecar: GET /node-types).

export type PortKind = "wolumen" | "segmentacja" | "segment" | "punkty" | "tabela" | "liczba" | "mesh";

export interface PortSchema {
  id: string;
  label: string;
  kind: PortKind;
  multi: boolean;
  optional?: boolean;
}

export interface ParamSchema {
  key: string;
  label: string;
  type: "number" | "int" | "select" | "bool" | "volume" | "mesh" | "points" | "strokes" | "markups";
  default: unknown;
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string;
  options: { value: string; label: string }[];
  help: string;
  showIf: [string, unknown] | null;
}

export interface NodeTypeSchema {
  id: string;
  label: string;
  domain: string;
  stage: "dane" | "przetwarzanie" | "wynik";
  description: string;
  inputs: PortSchema[];
  outputs: PortSchema[];
  params: ParamSchema[];
  cost: "light" | "heavy";
  widget: string; // custom card editor instead of generic params (e.g. "cropbox")
  version: number;
}

export interface GNode {
  id: string;
  type: string;
  x: number;
  y: number;
  params: Record<string, unknown>;
}

export interface GEdge {
  id: string;
  from: string;
  fromSocket: string;
  to: string;
  toSocket: string;
}

export interface GraphDoc {
  nodes: GNode[];
  edges: GEdge[];
  view: { x: number; y: number; zoom: number };
  display?: string | null; // node whose output the viewports show
}

export interface GraphMeta {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
}

/** Same colours as the CSS --port-* tokens (kept here for SVG edges). */
export const PORT_COLORS: Record<PortKind, string> = {
  wolumen: "#5b9bd5",
  segmentacja: "#b48ce0",
  segment: "#7bc47f",
  punkty: "#f2994a",
  tabela: "#f06292",
  liczba: "#90a4ae",
  mesh: "#4db6ac",
};

export const PORT_LABELS: Record<PortKind, string> = {
  wolumen: "Wolumen",
  segmentacja: "Segmentacja",
  segment: "Segment",
  punkty: "Punkty",
  tabela: "Tabela",
  liczba: "Liczba",
  mesh: "Mesh",
};
