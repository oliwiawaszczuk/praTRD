import { untrack } from "svelte";
// Thin client for the Python sidecar. JSON helpers here; binary (volume/slice) helpers
// arrive with the data stages and return ArrayBuffers without any JSON round-trip.

import { inTauri } from "./tauri.ts";

// The Tauri shell picks a free port per launch (see lib.rs `sidecar_port`). In a plain
// browser (`pnpm dev` + sidecar started by hand) 7433, or VITE_PRATRD_PORT when another
// local app already holds that port.
const DEFAULT_PORT = Number(import.meta.env.VITE_PRATRD_PORT ?? 7433);
let base = `http://127.0.0.1:${DEFAULT_PORT}`;

export const sidecarBase = (): string => base;

async function resolveBase(): Promise<void> {
  if (!inTauri()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  base = `http://127.0.0.1:${await invoke<number>("sidecar_port")}`;
}

// Requests in flight (except cheap ones like /health): drives the global loading bar.
let inflight = $state(0);
export const requestsInFlight = (): number => inflight;
export async function tracked<T>(p: Promise<T>): Promise<T> {
  // untrack: called from inside effects — reading the counter there would make every such
  // effect depend on it and re-run on each request (effect_update_depth_exceeded)
  untrack(() => inflight++);
  try {
    return await p;
  } finally {
    untrack(() => inflight--);
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function errorFrom(r: Response): Promise<ApiError> {
  let detail = `${r.status} ${r.statusText}`;
  try {
    const body = await r.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // non-JSON error body
  }
  return new ApiError(r.status, detail);
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await tracked(fetch(base + path, { signal }));
  if (!r.ok) throw await errorFrom(r);
  return r.json() as Promise<T>;
}

export async function sendJson<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
  opts: { keepalive?: boolean } = {},
): Promise<T> {
  const r = await tracked(fetch(base + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    keepalive: opts.keepalive,
  }));
  if (!r.ok) throw await errorFrom(r);
  return r.json() as Promise<T>;
}

export interface Health {
  app: string;
  version: string;
  uptime_s: number;
}

/** Polls /health until the sidecar answers. Python + numpy cold start is ~1–3 s,
 * a first PyInstaller launch on Windows can be much slower (AV scan), hence 60 s. */
export async function waitForSidecar(
  onTick?: (elapsedMs: number) => void,
  timeoutMs = 60_000,
): Promise<Health> {
  await resolveBase();
  const t0 = performance.now();
  let delay = 50;
  while (performance.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${base}/health`);
      if (r.ok) {
        const h = (await r.json()) as Health;
        if (h.app === "praTRD") return h;
      }
    } catch {
      // not up yet
    }
    onTick?.(performance.now() - t0);
    await new Promise((res) => setTimeout(res, delay));
    delay = Math.min(delay * 1.5, 400);
  }
  throw new Error(`Sidecar nie odpowiedział w ciągu ${timeoutMs / 1000} s`);
}

export interface BinaryResponse<M> {
  meta: M;
  buffer: ArrayBuffer;
}

/** Raw voxels: body is little-endian data, geometry in the X-Meta header. No JSON parse,
 * no copy — callers wrap `buffer` in the matching TypedArray view. */
export async function getBinary<M>(path: string, signal?: AbortSignal): Promise<BinaryResponse<M>> {
  const r = await tracked(fetch(base + path, { signal }));
  if (!r.ok) throw await errorFrom(r);
  const meta = JSON.parse(r.headers.get("X-Meta") ?? "{}") as M;
  return { meta, buffer: await r.arrayBuffer() };
}

export const wsUrl = (path: string): string => base.replace(/^http/, "ws") + path;
