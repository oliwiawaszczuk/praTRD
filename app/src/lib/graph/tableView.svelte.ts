// Which node's table is open in the table window (live: follows re-evaluation).

import { bestRun } from "./evaluation.svelte.ts";
import type { TableValue } from "./tables.ts";

let open = $state<{ nodeId: string; socket: string } | null>(null);

export const tableView = {
  get open() {
    return open;
  },
};

export function openTable(nodeId: string, socket: string): void {
  open = { nodeId, socket };
}

export function closeTable(): void {
  open = null;
}

/** The current table of a node's output socket (full resolution if computed, else preview). */
export function tableOf(nodeId: string, socket: string): TableValue | null {
  const o = bestRun(nodeId)?.outputs?.[socket];
  return o && o.kind === "tabela" && "value" in o ? (o.value as TableValue) : null;
}
