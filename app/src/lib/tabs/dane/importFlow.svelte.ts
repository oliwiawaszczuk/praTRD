// Import flow: paths → scan job → candidate dialog → one import job per series.
// Shared by the toolbar buttons and window-wide file drop.

import { sendJson } from "#lib/core/api.svelte.ts";
import { waitJob } from "#lib/core/events.svelte.ts";
import { activeWorkspaceId } from "#lib/core/workspace.svelte.ts";
import { showError, showInfo } from "#lib/ui/dialogs.svelte.ts";

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

export async function scanPaths(paths: string[]): Promise<void> {
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
  try {
    await sendJson("POST", `/workspaces/${activeWorkspaceId()}/import`, { scanId, ids, anonymize });
  } catch (e) {
    await showError("Import nie powiódł się", e);
  }
}
