// "tabela" values (pomiary nodes): columns + rows + an optional chart hint for the card.
// CSV for a Polish Excel: ";" separator, decimal comma, units in the header.

import { sendJson } from "#lib/core/api.svelte.ts";
import { inTauri } from "#lib/core/tauri.ts";

export interface TableColumn {
  key: string;
  label: string;
  unit: string;
}

export type TableChartHint =
  | { type: "bars"; label: string; value: string; color?: string }
  | { type: "histogram"; x: string; y: string }
  | { type: "line"; x: string; y: string };

export interface TableValue {
  title: string;
  columns: TableColumn[];
  rows: Record<string, string | number | null>[];
  chart: TableChartHint | null;
}

export const header = (c: TableColumn) => (c.unit ? `${c.label} [${c.unit}]` : c.label);

/** Columns that have at least one value (e.g. no intensity stats without a volume). */
export function usedColumns(t: TableValue): TableColumn[] {
  return t.columns.filter((c) => t.rows.some((r) => r[c.key] !== null && r[c.key] !== undefined && r[c.key] !== ""));
}

function cell(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return String(v).replace(".", ",");
  return /[;"\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function toCsv(t: TableValue): string {
  const cols = usedColumns(t);
  const lines = [cols.map((c) => cell(header(c))).join(";")];
  for (const r of t.rows) lines.push(cols.map((c) => cell(r[c.key])).join(";"));
  return lines.join("\r\n") + "\r\n";
}

const fileName = (s: string) => (s || "tabela").replace(/[\\/:*?"<>|]+/g, "-").trim() + ".csv";

/** Save as CSV: the native Save dialog in the app (written by the sidecar), a download in a
 * plain browser. Resolves to the saved path / name, or null when cancelled. */
export async function exportCsv(t: TableValue): Promise<string | null> {
  const text = toCsv(t);
  if (!inTauri()) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
    a.download = fileName(t.title);
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    return a.download;
  }
  const { save } = await import("@tauri-apps/plugin-dialog");
  const path = await save({ title: "Zapisz tabelę", defaultPath: fileName(t.title), filters: [{ name: "CSV", extensions: ["csv"] }] });
  if (!path) return null;
  await sendJson("POST", "/export/csv", { path: path.toLowerCase().endsWith(".csv") ? path : `${path}.csv`, text });
  return path;
}
