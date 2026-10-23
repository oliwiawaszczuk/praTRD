// Tauri bridge. Every call degrades gracefully in a plain browser (`pnpm dev` without
// the shell), so the UI can still be developed against a manually started sidecar.

export const inTauri = (): boolean =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function pickDirectory(title: string): Promise<string | null> {
  if (!inTauri()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ directory: true, multiple: false, title });
  return typeof r === "string" ? r : null;
}

/** Folders or files (DICOM folders, NIfTI/NRRD files) to import. */
export async function pickImportPaths(kind: "folders" | "files"): Promise<string[]> {
  if (!inTauri()) return [];
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({
    directory: kind === "folders",
    multiple: true,
    title: kind === "folders" ? "Wybierz foldery z DICOM" : "Wybierz pliki (DICOM, NIfTI, NRRD, MHA, STL, OBJ, PLY)",
  });
  return Array.isArray(r) ? r : typeof r === "string" ? [r] : [];
}

/** Mesh files (STL / OBJ / PLY). */
export async function pickMeshFiles(): Promise<string[]> {
  if (!inTauri()) return [];
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({
    multiple: true,
    title: "Wybierz mesh (STL, OBJ, PLY)",
    filters: [{ name: "Mesh", extensions: ["stl", "obj", "ply", "STL", "OBJ", "PLY"] }],
  });
  return Array.isArray(r) ? r : typeof r === "string" ? [r] : [];
}

/** OS file drag & drop onto the window (HTML5 drop events carry no paths in a webview). */
export async function onFileDrop(cb: {
  over: (on: boolean) => void;
  drop: (paths: string[]) => void;
}): Promise<() => void> {
  if (!inTauri()) return () => {};
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  return getCurrentWebview().onDragDropEvent((e) => {
    const p = e.payload;
    if (p.type === "enter" || p.type === "over") cb.over(true);
    else if (p.type === "leave") cb.over(false);
    else if (p.type === "drop") {
      cb.over(false);
      if (p.paths.length) cb.drop(p.paths);
    }
  });
}

export type MenuAction = "new" | "open" | "import" | "export";

export async function onWorkspaceMenu(cb: (a: MenuAction) => void): Promise<() => void> {
  if (!inTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen<MenuAction>("workspace-menu", (e) => cb(e.payload));
}

/** The shell intercepts the window close and emits `close-requested`; we flush pending
 * debounced saves, then let Rust destroy the window (which also stops the sidecar). */
export async function onCloseRequested(beforeClose: () => Promise<void>): Promise<() => void> {
  if (!inTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return listen("close-requested", async () => {
    try {
      await Promise.race([beforeClose(), new Promise((r) => setTimeout(r, 1500))]);
    } finally {
      await getCurrentWindow().destroy();
    }
  });
}

/** Native "Save as" for a file the sidecar writes (the webview has no file-system access);
 * a download in a plain browser. Resolves to the chosen path, or null when cancelled. */
export async function saveFileDialog(defaultName: string, ext: string, label: string): Promise<string | null> {
  if (!inTauri()) return null;
  const { save } = await import("@tauri-apps/plugin-dialog");
  const path = await save({ title: "Zapisz", defaultPath: defaultName, filters: [{ name: label, extensions: [ext] }] });
  if (!path) return null;
  return path.toLowerCase().endsWith(`.${ext}`) ? path : `${path}.${ext}`;
}

export function browserDownload(blob: Blob, name: string): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
