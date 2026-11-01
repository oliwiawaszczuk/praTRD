// Kreator state: the list of user nodes, the open draft (manifest + code), save / delete /
// import / export and test runs. The draft survives a restart (app setting "kreator"),
// so unsaved work is never lost; saving re-registers the node and the palette reloads
// itself on the sidecar's "node-types" event.

import { ApiError, getJson, sendJson } from "#lib/core/api.svelte.ts";
import { getSetting, setSetting } from "#lib/core/appSettings.svelte.ts";
import { onJobProgress, waitJob } from "#lib/core/events.svelte.ts";
import { activeWorkspaceId } from "#lib/core/workspace.svelte.ts";
import { graph } from "#lib/graph/store.svelte.ts";
import { confirmAction, promptText, showError } from "#lib/ui/dialogs.svelte.ts";
import { toast } from "#lib/ui/toast.svelte.ts";
import { codeSkeleton, uniqueName, type Manifest, type Template } from "./model.ts";

export interface CustomEntry {
  slug: string;
  label: string;
  domain: string;
  updatedAt: string;
  error: string;
}

export type Source =
  | { source: "fantom" }
  | { source: "seria"; vid: string }
  | { source: "graf"; node: string; socket: string }
  | { source: "brak" };

export interface Check {
  id: string;
  label: string;
  level: "ok" | "info" | "warn" | "fail";
  message?: string;
  line?: number | null;
}

export interface TestResult {
  state: "done" | "error" | "blocked";
  error: { message: string; line: number | null; trace: string; module?: string | null } | null;
  outputs: Record<string, { kind: string; ref?: string; info?: Record<string, unknown>; value?: unknown }>;
  inputs: Record<string, { kind: string; ref?: string; info?: Record<string, unknown>; value?: unknown }>;
  logs: string[];
  stats: Record<string, Record<string, unknown>>;
  checks: Check[];
  ms: number;
}

interface Draft {
  slug: string | null; // saved name being edited; null = never saved
  manifest: Manifest;
  code: string;
  sources: Record<string, Source>;
}

let list = $state.raw<CustomEntry[]>([]);
let draft = $state<Draft | null>(null);
let savedSig = $state(""); // manifest + code as last saved — dirty = differs
let saving = $state(false);
let testing = $state<string | null>(null); // job id
let result = $state.raw<TestResult | null>(null);
let resultSig = $state(""); // what the result was computed from (stale marker)
let codeError = $state.raw<{ message: string; line: number | null } | null>(null);

export const kreator = {
  get list() {
    return list;
  },
  get draft() {
    return draft;
  },
  get dirty() {
    return !!draft && sig(draft) !== savedSig;
  },
  get saving() {
    return saving;
  },
  get testing() {
    return testing !== null;
  },
  get result() {
    return result;
  },
  get resultStale() {
    return !!draft && !!result && sig(draft, true) !== resultSig;
  },
  get codeError() {
    return codeError;
  },
};

const sig = (d: Draft, withSources = false): string =>
  JSON.stringify(withSources ? [d.manifest, d.code, d.sources] : [d.manifest, d.code]);

/** Every edit goes through here: keeps the restart-safe copy in the app settings. */
export function touch(): void {
  if (draft) setSetting("kreator", $state.snapshot(draft));
}

export async function loadList(): Promise<void> {
  list = (await getJson<{ nodes: CustomEntry[] }>("/custom-nodes")).nodes;
}

export async function restore(): Promise<void> {
  await loadList();
  const d = getSetting<Draft | null>("kreator", null);
  // "edit" on a graph card may have opened a node before this first mount finished
  if (!d?.manifest || draft) return;
  draft = d;
  savedSig = "";
  if (d.slug && list.some((n) => n.slug === d.slug)) {
    const saved = await getJson<{ manifest: Manifest; code: string }>(`/custom-nodes/${d.slug}`);
    savedSig = JSON.stringify([strip(saved.manifest), saved.code]);
  } else if (d.slug) {
    d.slug = null; // deleted meanwhile — the draft becomes a new node
  }
}

function strip(m: Manifest & { createdAt?: string; updatedAt?: string }): Manifest {
  const { createdAt: _c, updatedAt: _u, ...rest } = m;
  return rest as Manifest;
}

async function leaveDraft(): Promise<boolean> {
  if (!kreator.dirty) return true;
  return confirmAction("Niezapisane zmiany", `„${draft!.manifest.label}” ma niezapisane zmiany. Porzucić je?`, {
    confirmText: "Porzuć",
    danger: true,
  });
}

export async function openNode(slug: string): Promise<void> {
  if (draft?.slug === slug) return;
  if (!(await leaveDraft())) return;
  const d = await getJson<{ manifest: Manifest; code: string }>(`/custom-nodes/${slug}`);
  const m = strip(d.manifest);
  draft = { slug, manifest: m, code: d.code, sources: {} };
  savedSig = JSON.stringify([m, d.code]);
  result = null;
  codeError = null;
  touch();
}

export async function newFromTemplate(t: Template): Promise<void> {
  if (!(await leaveDraft())) return;
  const manifest: Manifest = {
    ...structuredClone(t.manifest),
    slug: uniqueName(t.slug, slugs(), 40),
  };
  draft = { slug: null, manifest, code: t.code ?? codeSkeleton(manifest), sources: {} };
  savedSig = "";
  result = null;
  codeError = null;
  touch();
}

const slugs = () => list.map((n) => n.slug);

/** The name is UI text (Polish); the id is code (English) and never follows the name. */
export function setLabel(label: string): void {
  if (!draft) return;
  draft.manifest.label = label;
  touch();
}

export async function save(): Promise<void> {
  if (!draft || saving) return;
  saving = true;
  try {
    const body = { manifest: $state.snapshot(draft.manifest), code: draft.code };
    const path = `/custom-nodes/${draft.slug ?? "_"}`;
    let saved: { manifest: Manifest; code: string };
    try {
      saved = await sendJson("PUT", path, body);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409)) throw e;
      const name = await promptText(`Identyfikator „${draft.manifest.slug}” jest zajęty`, {
        label: "Nowy identyfikator (małe litery, cyfry, _)",
        value: uniqueName(draft.manifest.slug, slugs(), 40),
        confirmText: "Zapisz",
      });
      if (!name) return;
      draft.manifest.slug = name;
      saved = await sendJson("PUT", path, { ...body, manifest: { ...body.manifest, slug: name } });
    }
    // the sidecar normalizes the manifest (defaults, clamping) — continue from its version
    draft.manifest = strip(saved.manifest);
    draft.slug = saved.manifest.slug;
    savedSig = JSON.stringify([draft.manifest, saved.code]);
    touch();
    await loadList();
    toast(`Zapisano „${saved.manifest.label}” — jest w palecie Sceny`, { icon: "check" });
  } catch (e) {
    await showError("Nie udało się zapisać", e);
  } finally {
    saving = false;
  }
}

export async function remove(slug: string): Promise<void> {
  const n = list.find((x) => x.slug === slug);
  const ok = await confirmAction(
    "Usuń node",
    `Usunąć „${n?.label ?? slug}”? Karty tego node'a w grafach zostaną oznaczone jako brakujące.`,
    { confirmText: "Usuń", danger: true },
  );
  if (!ok) return;
  await sendJson("DELETE", `/custom-nodes/${slug}`);
  if (draft?.slug === slug) {
    draft = null;
    result = null;
    setSetting("kreator", null);
  }
  await loadList();
}

export function duplicate(): void {
  if (!draft) return;
  const label = `${draft.manifest.label} (kopia)`;
  draft = {
    ...$state.snapshot(draft),
    slug: null,
    manifest: { ...$state.snapshot(draft.manifest), label, slug: uniqueName(`${draft.manifest.slug}_copy`, slugs(), 40) },
  };
  savedSig = "";
  touch();
}

// ── code check (on edit, debounced — never polled) ─────────────────────────────

let checkTimer: ReturnType<typeof setTimeout> | null = null;
export function setCode(code: string): void {
  if (!draft) return;
  draft.code = code;
  touch();
  if (checkTimer) clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    const r = await sendJson<{ ok: boolean; message: string; line: number | null }>("POST", "/custom-nodes/check", { code });
    if (draft?.code === code) codeError = r.ok ? null : { message: r.message, line: r.line };
  }, 350);
}

// ── test ─────────────────────────────────────────────────────────────────────

export async function runTest(): Promise<void> {
  if (!draft || testing) return;
  const d = $state.snapshot(draft);
  const params = Object.fromEntries(d.manifest.params.map((p) => [p.key, p.default]));
  const usesGraph = Object.values(d.sources).some((s) => s.source === "graf");
  try {
    const { jobId } = await sendJson<{ jobId: string }>("POST", "/custom-nodes/test", {
      wid: activeWorkspaceId(),
      manifest: d.manifest,
      code: d.code,
      params,
      inputs: d.sources,
      graph: usesGraph ? $state.snapshot(graph.doc) : undefined,
    });
    testing = jobId;
    const job = await waitJob(jobId);
    if (job.state === "done") {
      result = job.result as TestResult;
      resultSig = sig(d as Draft, true);
    } else if (job.state === "error") {
      await showError("Test nie wystartował", job.error);
    }
  } catch (e) {
    await showError("Test nie wystartował", e);
  } finally {
    testing = null;
  }
}

// ── one-file exchange ───────────────────────────────────────────────────────────

export async function exportNode(slug: string): Promise<void> {
  const { inTauri } = await import("#lib/core/tauri.ts");
  if (!inTauri()) return;
  const { save: saveDialog } = await import("@tauri-apps/plugin-dialog");
  const path = await saveDialog({
    title: "Eksport node'a",
    defaultPath: `${slug}.pratrdnode`,
    filters: [{ name: "Node praTRD", extensions: ["pratrdnode"] }],
  });
  if (!path) return;
  const full = path.endsWith(".pratrdnode") ? path : `${path}.pratrdnode`;
  await sendJson("POST", `/custom-nodes/${slug}/export`, { path: full });
  toast(`Zapisano ${full.split(/[\\/]/).pop()}`, { icon: "check" });
}

/** Opens the file as a new draft (not saved yet): the name conflict, if any, is asked on
 * save — an import never replaces an existing node by itself. */
export async function importNode(): Promise<void> {
  const { inTauri } = await import("#lib/core/tauri.ts");
  if (!inTauri()) return;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const path = await open({ title: "Import node'a", filters: [{ name: "Node praTRD", extensions: ["pratrdnode"] }] });
  if (typeof path !== "string") return;
  if (!(await leaveDraft())) return;
  try {
    const d = await sendJson<{ manifest: Manifest; code: string; exists: boolean }>("POST", "/custom-nodes/read-file", { path });
    draft = { slug: null, manifest: d.manifest, code: d.code, sources: {} };
    savedSig = "";
    result = null;
    touch();
    toast(d.exists ? "Wczytano — identyfikator zajęty, zapis zapyta o nowy" : "Wczytano — zapisz, aby dodać do palety", { icon: "folderIn" });
  } catch (e) {
    await showError("Nie udało się wczytać", e);
  }
}

// ── libraries (bundled + installed from PyPI into python_packages) ─────────────────

export interface Library {
  name: string;
  module?: string;
  version: string;
  snippet?: string;
  about?: string;
  modules?: string[];
}
interface Libraries {
  builtin: Library[];
  user: Library[];
  pipNames: Record<string, string>;
  canInstall: boolean;
}

let libs = $state.raw<Libraries | null>(null);
let installing = $state<string | null>(null); // spec being installed
let installMsg = $state("");

export const libraries = {
  get list() {
    return libs;
  },
  get installing() {
    return installing;
  },
  get message() {
    return installMsg;
  },
};

export async function loadLibraries(): Promise<void> {
  libs = await getJson<Libraries>("/custom-nodes/libraries");
}

/** Every module name code can import (editor completions). */
export function importableModules(): string[] {
  if (!libs) return [];
  return [...libs.builtin.map((l) => l.module!), ...libs.user.flatMap((l) => l.modules ?? [])];
}

/** PyPI name for a missing import (`sklearn` → `scikit-learn`). */
export const pipNameFor = (module: string): string => libs?.pipNames[module] ?? module.replace(/_/g, "-");

export async function installLibrary(spec: string): Promise<boolean> {
  spec = spec.trim();
  if (!spec || installing) return false;
  installing = spec;
  installMsg = "";
  try {
    const { jobId } = await sendJson<{ jobId: string }>("POST", "/custom-nodes/libraries/install", { spec });
    const stop = onJobProgress(jobId, (m) => (installMsg = m));
    const job = await waitJob(jobId);
    stop();
    if (job.state === "error") {
      await showError(`Nie udało się zainstalować ${spec}`, job.error.replace(/^PackageError: /, ""));
      return false;
    }
    if (job.state !== "done") return false;
    const r = job.result as { installed: string[]; skipped: string[]; conflicts: string[] };
    await loadLibraries();
    if (r.conflicts.length) {
      await showError(
        "Zainstalowano, ale wersje się różnią",
        `Aplikacja używa swoich wersji (nie podmienia ich):\n${r.conflicts.join("\n")}\n\nJeśli paczka nie zadziała, wybierz jej starszą wersję, np. nazwa==1.2.`,
      );
    } else {
      toast(r.installed.length ? `Zainstalowano: ${r.installed.map((x) => x.split("==")[0]).join(", ")}` : `${spec} już jest dostępne`, {
        icon: "check",
      });
    }
    return true;
  } catch (e) {
    await showError(`Nie udało się zainstalować ${spec}`, e);
    return false;
  } finally {
    installing = null;
    installMsg = "";
  }
}

export async function uninstallLibrary(name: string): Promise<void> {
  const ok = await confirmAction("Usuń bibliotekę", `Usunąć ${name}? Node'y, które jej używają, przestaną działać (zmiana w pełni po restarcie appki).`, {
    confirmText: "Usuń",
    danger: true,
  });
  if (!ok) return;
  await sendJson("DELETE", `/custom-nodes/libraries/${encodeURIComponent(name)}`);
  await loadLibraries();
}
