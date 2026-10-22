// Global settings shared by every workspace (app_settings.json): canvas sensitivity,
// GPU/RAM budgets, anonymization defaults, shortcuts. Rare by design — default to wsGet/wsSet.

import { getJson, sendJson } from "./api.svelte.ts";
import { debouncedSaver } from "./persisted.ts";

let cache = $state<Record<string, unknown>>({});

const saver = debouncedSaver(500, ({ keepalive }) =>
  sendJson("PUT", "/app_settings", $state.snapshot(cache), { keepalive }),
);

export async function loadAppSettings(): Promise<void> {
  cache = await getJson<Record<string, unknown>>("/app_settings");
}

export function getSetting<T>(key: string, fallback: T): T {
  return key in cache ? (cache[key] as T) : fallback;
}

export function setSetting(key: string, value: unknown): void {
  // Skip no-op writes of primitives; objects are always saved (callers may pass a
  // mutated copy, and a proxy never === its raw source anyway).
  if (typeof value !== "object" && cache[key] === value) return;
  cache[key] = value;
  saver.schedule();
}

export const flushAppSettings = saver.flush;
