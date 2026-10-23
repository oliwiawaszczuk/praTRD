// The value currently flowing INTO a node's input socket (best available run upstream).

import { bestRun, VOLUME_KINDS, type VolumeOut } from "./evaluation.svelte.ts";
import { graph } from "./store.svelte.ts";

export function upstreamVolume(nodeId: string, socket: string): VolumeOut | null {
  const e = graph.doc.edges.find((x) => x.to === nodeId && x.toSocket === socket);
  if (!e) return null;
  const o = bestRun(e.from)?.outputs?.[e.fromSocket];
  return o && VOLUME_KINDS.includes(o.kind) ? (o as VolumeOut) : null;
}
