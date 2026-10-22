// Live sidecar events over one WebSocket: background jobs (progress / state) and
// library changes. Reconnects with backoff; every (re)connect starts with a snapshot,
// so no event can be "missed" across a reconnect.

import { sendJson, wsUrl } from "./api.svelte.ts";

export type JobState = "queued" | "running" | "done" | "error" | "cancelled";

export interface Job {
  id: string;
  kind: string;
  title: string;
  wid: string;
  state: JobState;
  progress: number;
  message: string;
  result: unknown;
  error: string;
  created: number;
}

type Msg =
  | { type: "snapshot"; jobs: Job[] }
  | { type: "job"; job: Job }
  | { type: "library"; wid: string }
  | ({ type: string } & Record<string, unknown>);

let jobs = $state<Record<string, Job>>({});
let connected = $state(false);

const waiters = new Map<string, ((j: Job) => void)[]>();
// Jobs already finished when a snapshot arrived (e.g. before this page loaded):
// history, not news — the job tray does not announce them.
const stale = new Set<string>();
const libraryListeners = new Set<(wid: string) => void>();
const typedListeners = new Map<string, Set<(msg: Record<string, unknown>) => void>>();

const terminal = (s: JobState) => s === "done" || s === "error" || s === "cancelled";

function settle(job: Job): void {
  if (!terminal(job.state)) return;
  const ws = waiters.get(job.id);
  if (ws) {
    waiters.delete(job.id);
    for (const w of ws) w(job);
  }
}

function onMessage(msg: Msg): void {
  if (msg.type === "snapshot") {
    const next: Record<string, Job> = {};
    for (const j of (msg as { jobs: Job[] }).jobs) {
      next[j.id] = j;
      if (terminal(j.state)) stale.add(j.id);
    }
    jobs = next;
    for (const j of Object.values(next)) settle(j);
  } else if (msg.type === "job") {
    const job = (msg as { job: Job }).job;
    jobs[job.id] = job;
    settle(job);
  } else if (msg.type === "library") {
    for (const l of libraryListeners) l((msg as { wid: string }).wid);
  } else {
    for (const l of typedListeners.get(msg.type) ?? []) l(msg as Record<string, unknown>);
  }
}

let socket: WebSocket | null = null;
let retry = 250;

export function connectEvents(): void {
  if (socket) return;
  const ws = new WebSocket(wsUrl("/ws"));
  socket = ws;
  ws.onopen = () => {
    connected = true;
    retry = 250;
  };
  ws.onmessage = (e) => onMessage(JSON.parse(e.data as string) as Msg);
  ws.onclose = () => {
    connected = false;
    socket = null;
    setTimeout(connectEvents, retry);
    retry = Math.min(retry * 2, 4000);
  };
}

export const allJobs = (): Job[] => Object.values(jobs).sort((a, b) => b.created - a.created);
export const eventsConnected = (): boolean => connected;
export const isStaleJob = (id: string): boolean => stale.has(id);

export function waitJob(id: string): Promise<Job> {
  const known = jobs[id];
  if (known && terminal(known.state)) return Promise.resolve(known);
  return new Promise((res) => {
    const list = waiters.get(id) ?? [];
    list.push(res);
    waiters.set(id, list);
  });
}

export function cancelJob(id: string): Promise<unknown> {
  return sendJson("POST", `/jobs/${id}/cancel`);
}

export function onLibraryChanged(cb: (wid: string) => void): () => void {
  libraryListeners.add(cb);
  return () => libraryListeners.delete(cb);
}

/** Subscribe to any other event type (e.g. "graph-node"). */
export function onEvent(type: string, cb: (msg: Record<string, unknown>) => void): () => void {
  let set = typedListeners.get(type);
  if (!set) typedListeners.set(type, (set = new Set()));
  set.add(cb);
  return () => set!.delete(cb);
}
