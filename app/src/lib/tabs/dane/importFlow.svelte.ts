// Import flow: paths → scan job → candidate dialog → one import job per series.
// Shared by the toolbar buttons and window-wide file drop. Mesh files (STL / OBJ / PLY) skip
// the scan and go straight to the workspace's mesh library.

import { sendJson } from "#lib/core/api.svelte.ts";
import { waitJob } from "#lib/core/events.svelte.ts";
import { libraryVolumes } from "#lib/core/library.svelte.ts";
import { noteImport } from "./folders.svelte.ts";
import { activeWorkspaceId } from "#lib/core/workspace.svelte.ts";
import { importMeshes, isMeshPath } from "#lib/core/meshes.svelte.ts";
import { showError, showInfo } from "#lib/ui/dialogs.svelte.ts";
import { toast } from "#lib/ui/toast.svelte.ts";

export interface CandidateSummary {
  id: number;
  kind: "dicom" | "nifti" | "itk";
  name: string;
  size: [number, number, number];
  spacing: [number, number, number];
  dtype: string;
  rawBytes: number;
  warnings: string[];
  alreadyImported: boolean;
  modality?: string;
  patientName?: string;
  patientId?: string;
  studyDescription?: string;
  studyDate?: string;
  seriesNumber?: string;
  nFiles?: number;
}

interface ScanResult {
  scanId: string;
  candidates: CandidateSummary[];
}

let scanning = $state(false);
let pending = $state<ScanResult | null>(null);

export const isScanning = (): boolean => scanning;
export const pendingScan = (): ScanResult | null => pending;
export const closeScan = (): void => {
  pending = null;
};

async function importMeshFiles(paths: string[]): Promise<void> {
  try {
    const r = await importMeshes(paths);
    for (const m of r.added) toast(`Mesh „${m.name}” w bibliotece — node „Plik mesha” w Scenie`, { icon: "mesh", ms: 5000 });
    if (r.errors.length) await showError("Nie udało się wczytać mesha", r.errors.map((e) => e.error).join("\n"));
  } catch (e) {
    await showError("Nie udało się wczytać mesha", e);
  }
}

export async function scanPaths(paths: string[]): Promise<void> {
  const meshes = paths.filter(isMeshPath);
  if (meshes.length) {
    await importMeshFiles(meshes);
    paths = paths.filter((p) => !isMeshPath(p));
  }
  if (!paths.length || scanning) return;
  scanning = true;
  try {
    const wid = activeWorkspaceId();
    const { jobId } = await sendJson<{ jobId: string }>("POST", `/workspaces/${wid}/scan`, { paths });
    const job = await waitJob(jobId);
    if (job.state !== "done") {
      if (job.state === "error") await showError("Skanowanie nie powiodło się", job.error);
      return;
    }
    const res = job.result as ScanResult;
    if (!res.candidates.length) {
      await showInfo("Nic do zaimportowania", "W wybranych miejscach nie znaleziono serii DICOM ani plików NIfTI/NRRD/MHA.");
      return;
    }
    pending = res;
  } catch (e) {
    await showError("Skanowanie nie powiodło się", e);
  } finally {
    scanning = false;
  }
}

export async function importSelected(ids: number[], anonymize: boolean): Promise<void> {
  if (!pending || !ids.length) return;
  const { scanId } = pending;
  pending = null;
  noteImport(libraryVolumes().map((v) => v.id));
  try {
    await sendJson("POST", `/workspaces/${activeWorkspaceId()}/import`, { scanId, ids, anonymize });
  } catch (e) {
    await showError("Import nie powiódł się", e);
  }
}
