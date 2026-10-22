// The value currently flowing INTO a node's input socket (best available run upstream).

import { bestRun, type VolumeOut } from "./evaluation.svelte.ts";
import { graph } from "./store.svelte.ts";

export function upstreamVolume(nodeId: string, socket: string): VolumeOut | null {
  const e = graph.doc.edges.find((x) => x.to === nodeId && x.toSocket === socket);
  if (!e) return null;
  const o = bestRun(e.from)?.outputs?.[e.fromSocket];
  return o && "ref" in o ? (o as VolumeOut) : null;
}
