// Node types from the sidecar — the frontend has no hard-coded node definitions.

import { getJson } from "#lib/core/api.svelte.ts";
import type { NodeTypeSchema } from "./types.ts";

let types = $state.raw<NodeTypeSchema[]>([]);
let domains = $state.raw<Record<string, string>>({});
const byId = new Map<string, NodeTypeSchema>();

export async function loadNodeTypes(): Promise<void> {
  const s = await getJson<{ domains: Record<string, string>; types: NodeTypeSchema[] }>("/node-types");
  byId.clear();
  for (const t of s.types) byId.set(t.id, t);
  domains = s.domains;
  types = s.types;
}

export const nodeTypes = (): NodeTypeSchema[] => types;
export const domainLabels = (): Record<string, string> => domains;
export const nodeType = (id: string): NodeTypeSchema | undefined => (void types, byId.get(id));

export function defaultParams(t: NodeTypeSchema): Record<string, unknown> {
  return Object.fromEntries(t.params.map((p) => [p.key, p.default]));
}

export const DOMAIN_COLOR: Record<string, string> = {
  wolumen: "#5b9bd5",
  filtry: "#64b5f6",
  segmentacja: "#b48ce0",
  pomiary: "#f2994a",
  mesh: "#4db6ac",
};
