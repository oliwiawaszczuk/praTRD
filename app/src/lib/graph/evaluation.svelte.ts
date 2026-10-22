// Live evaluation ("Hybryda" from the Q&A):
//  * any SEMANTIC change (params, edges, nodes, display — not positions) → preview of the
//    whole graph, debounced 120 ms; the sidecar cancels the previous run of this graph;
//  * when idle for IDLE_FULL_MS and auto-full is on → full resolution for the displayed node;
//  * full results are dropped on every change (they'd be stale); preview results stay on
//    screen marked stale until the new ones arrive — no flicker while dragging a slider.

import { sendJson } from "#lib/core/api.svelte.ts";
import { getSetting } from "#lib/core/appSettings.svelte.ts";
import { allJobs, onEvent } from "#lib/core/events.svelte.ts";
import { activeWorkspaceId } from "#lib/core/workspace.svelte.ts";
import { nodeType } from "./registry.svelte.ts";
import { graph } from "./store.svelte.ts";

export type NodeRunState = "computing" | "done" | "error" | "blocked" | "stale";

export interface VolumeOut {
  kind: "wolumen" | "segment" | "segmentacja";
  ref: string;
  level: number;
  info: {
    name?: string;
    modality?: string;
    window?: { center: number; width: number };
    // segments
    ref?: string;
    color?: string;
    voxels?: number;
    ml?: number;
    labels?: { id: number; name: string; color: string }[];
    [k: string]: unknown;
  };
  geometry: { size: [number, number, number]; spacing: [number, number, number] };
}

export interface NodeRun {
  state: NodeRunState;
  error?: string;
  outputs?: Record<string, VolumeOut | { kind: string; value: unknown }>;
  ms?: number;
  cached?: boolean;
  sig: string; // signature of the graph that produced it
}

const PREVIEW_DEBOUNCE_MS = 120;
const IDLE_FULL_MS = 700;

let preview = $state<Record<string, NodeRun>>({});
let full = $state<Record<string, NodeRun>>({});
let previewJob = $state("");
let fullJob = $state("");
let sig = "";

export const runs = {
  get preview() {
    return preview;
  },
  get full() {
    return full;
  },
  get previewJob() {
    return previewJob;
  },
  get fullJob() {
    return fullJob;
  },
};

/** Semantic signature: positions and view are excluded on purpose. */
function signature(): string {
  const d = graph.doc;
  return JSON.stringify([
    d.nodes.map((n) => [n.id, n.type, n.params]),
    d.edges.map((e) => [e.from, e.fromSocket, e.to, e.toSocket]),
    d.display ?? null,
  ]);
}

async function post(quality: "preview" | "full", targets: string[]): Promise<string> {
  const r = await sendJson<{ jobId: string }>(
    "POST",
    `/workspaces/${activeWorkspaceId()}/graphs/${graph.activeId}/evaluate`,
    { graph: $state.snapshot(graph.doc), targets, quality },
  );
  return r.jobId;
}

/** Nodes whose results must be exact: the displayed one and every measurement table. */
function fullTargets(): string[] {
  const t = graph.doc.nodes
    .filter((n) => n.id === graph.doc.display || nodeType(n.type)?.outputs.some((o) => o.kind === "tabela"))
    .map((n) => n.id);
  return t;
}

export async function evaluateFull(): Promise<void> {
  const targets = fullTargets();
  if (!targets.length) return;
  fullJob = await post("full", targets);
}

let previewTimer: ReturnType<typeof setTimeout> | null = null;
let fullTimer: ReturnType<typeof setTimeout> | null = null;

function onChange(): void {
  // mark old results stale, drop full ones
  const next: Record<string, NodeRun> = {};
  for (const [k, v] of Object.entries(preview)) next[k] = { ...v, state: v.state === "done" ? "stale" : v.state };
  preview = next;
  full = {};
  if (previewTimer) clearTimeout(previewTimer);
  if (fullTimer) clearTimeout(fullTimer);
  if (!graph.doc.nodes.length) return;
  previewTimer = setTimeout(async () => {
    previewJob = await post("preview", graph.doc.nodes.map((n) => n.id));
  }, PREVIEW_DEBOUNCE_MS);
}

/** Start reacting to graph changes and sidecar events. Call inside a component $effect. */
export function startEvaluation(): () => void {
  const off = onEvent("graph-node", (m) => {
    if (m.wid !== activeWorkspaceId() || m.gid !== graph.activeId) return;
    const run: NodeRun = {
      state: m.state as NodeRunState,
      error: m.error as string | undefined,
      outputs: m.outputs as NodeRun["outputs"],
      ms: m.ms as number | undefined,
      cached: m.cached as boolean | undefined,
      sig,
    };
    const store = m.quality === "full" ? full : preview;
    // still computing → keep the last outputs on screen (stale) instead of blanking them
    const prev = store[m.node as string];
    if (run.state === "computing" && !run.outputs && prev?.outputs) run.outputs = prev.outputs;
    store[m.node as string] = run;
    // preview finished for the displayed node → schedule full resolution when idle. Also
    // after an error (e.g. no seeds yet): the full run still refreshes its inputs, so the
    // views show the input at full resolution to click seeds on.
    if (m.quality === "preview" && (m.state === "done" || m.state === "error") && fullTargets().includes(m.node as string)) {
      if (fullTimer) clearTimeout(fullTimer);
      if (getSetting("graphAutoFull", true))
        fullTimer = setTimeout(() => void evaluateFull(), IDLE_FULL_MS);
    }
  });

  let lastGraph = "";
  const stop = $effect.root(() => {
    $effect(() => {
      if (!graph.loaded) return;
      const s = signature();
      if (graph.activeId !== lastGraph) {
        lastGraph = graph.activeId;
        preview = {};
        full = {};
      }
      if (s === sig) return;
      sig = s;
      onChange();
    });
  });
  return () => {
    off();
    stop();
    if (previewTimer) clearTimeout(previewTimer);
    if (fullTimer) clearTimeout(fullTimer);
  };
}

/** Best available run of a node: full if present, else preview. */
export function bestRun(nodeId: string): (NodeRun & { quality: "full" | "preview" }) | null {
  const f = full[nodeId];
  if (f?.state === "done") return { ...f, quality: "full" };
  const p = preview[nodeId];
  return p ? { ...p, quality: "preview" } : null;
}

/** Progress (0..1) of the job currently computing this node, if any. */
export function jobProgress(quality: "preview" | "full"): number | null {
  const id = quality === "full" ? fullJob : previewJob;
  const j = allJobs().find((x) => x.id === id);
  return j && j.state === "running" ? j.progress : null;
}
