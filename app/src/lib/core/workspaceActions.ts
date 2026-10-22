// User-facing workspace flows (dialogs + store calls), shared by the native menu and
// the Settings tab so both behave identically.

import { confirmAction, promptText, showError, showInfo } from "#lib/ui/dialogs.svelte.ts";
import { pickDirectory } from "./tauri";
import {
  activeWorkspace,
  createWorkspace,
  deleteWorkspace,
  exportWorkspace,
  importWorkspace,
  renameWorkspace,
  type WorkspaceMeta,
} from "./workspace.svelte";

async function guarded(title: string, fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch (e) {
    await showError(title, e);
  }
}

export const newWorkspaceFlow = () =>
  guarded("Nie udało się utworzyć workspace'u", async () => {
    const name = await promptText("Nowy workspace", { label: "Nazwa", confirmText: "Utwórz" });
    if (name) await createWorkspace(name);
  });

export const renameWorkspaceFlow = (ws: WorkspaceMeta) =>
  guarded("Nie udało się zmienić nazwy", async () => {
    const name = await promptText("Zmień nazwę", { value: ws.name, confirmText: "Zapisz" });
    if (name && name !== ws.name) await renameWorkspace(ws.id, name);
  });

export const deleteWorkspaceFlow = (ws: WorkspaceMeta) =>
  guarded("Nie udało się usunąć workspace'u", async () => {
    const ok = await confirmAction(
      "Usunąć workspace?",
      `„${ws.name}” zostanie trwale usunięty z dysku razem z zaimportowanymi seriami, grafami i wynikami.`,
      { confirmText: "Usuń", danger: true },
    );
    if (ok) await deleteWorkspace(ws.id);
  });

export const exportWorkspaceFlow = (ws: WorkspaceMeta | undefined = activeWorkspace()) =>
  guarded("Eksport nie powiódł się", async () => {
    if (!ws) return;
    const dir = await pickDirectory(`Eksportuj „${ws.name}” do folderu`);
    if (!dir) return;
    const path = await exportWorkspace(ws.id, dir);
    await showInfo("Wyeksportowano", path);
  });

export const importWorkspaceFlow = () =>
  guarded("Import nie powiódł się", async () => {
    const dir = await pickDirectory("Wybierz folder workspace'u praTRD");
    if (dir) await importWorkspace(dir);
  });
