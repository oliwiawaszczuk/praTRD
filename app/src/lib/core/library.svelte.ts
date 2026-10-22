// Volume library of the active workspace (light summaries; voxels stay in the sidecar).

import { getJson, sendJson, sidecarBase } from "./api.svelte.ts";
import { onLibraryChanged } from "./events.svelte.ts";
import { activeWorkspaceId } from "./workspace.svelte.ts";

export type Axis = "i" | "j" | "k";

export interface VolumeEntry {
  id: string;
  name: string;
  kind: "scalar";
  source: "dicom" | "nifti" | "itk";
  sourcePath: string | null;
  anonymized: boolean;
  createdAt: string;
  size: [number, number, number];
  spacing: [number, number, number];
  dtype: string;
  levels: number;
  bytesOnDisk: number;
  window: { center: number; width: number };
  stats: { min: number; max: number; p1: number; p99: number };
  planes: Record<Axis, string>;
  warnings: string[];
  importSeconds: number;
  modality?: string;
  patientName?: string;
  patientSex?: string;
  patientAge?: string;
  studyDescription?: string;
  studyDate?: string;
  seriesNumber?: string;
  bodyPart?: string;
  manufacturer?: string;
  transferSyntax?: string;
  nFiles?: number;
}

export interface LevelGeometry {
  size: [number, number, number];
  spacing: [number, number, number];
  origin: [number, number, number];
  direction: number[];
}

export interface VolumeMeta {
  dtype: string;
  levels: LevelGeometry[];
  stats: VolumeEntry["stats"] & { histogram: number[]; p0_5: number; p99_5: number };
}

let volumes = $state<VolumeEntry[]>([]);
let loaded = $state(false);

const wsPath = () => `/workspaces/${activeWorkspaceId()}`;

export async function loadLibrary(): Promise<void> {
  volumes = await getJson<VolumeEntry[]>(`${wsPath()}/volumes`);
  loaded = true;
}

onLibraryChanged((wid) => {
  if (wid === activeWorkspaceId()) void loadLibrary();
});

export const libraryVolumes = (): VolumeEntry[] => volumes;
export const libraryLoaded = (): boolean => loaded;

export function thumbUrl(vid: string): string {
  return `${sidecarBase()}${wsPath()}/volumes/${vid}/thumb.png`;
}

export const volumeMeta = (vid: string, signal?: AbortSignal) =>
  getJson<VolumeMeta>(`${wsPath()}/volumes/${vid}/meta`, signal);

export async function renameVolume(vid: string, name: string): Promise<void> {
  const e = await sendJson<VolumeEntry>("PUT", `${wsPath()}/volumes/${vid}`, { name });
  volumes = volumes.map((v) => (v.id === vid ? e : v));
}

export async function deleteVolume(vid: string): Promise<void> {
  await sendJson("DELETE", `${wsPath()}/volumes/${vid}`);
  volumes = volumes.filter((v) => v.id !== vid);
}

export const volumePath = (vid: string): string => `${wsPath()}/volumes/${vid}`;
