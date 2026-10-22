<script lang="ts">
  // Full table of a measurement node: big chart, every column with units, CSV export.
  import Icon from "#lib/ui/Icon.svelte";
  import { num, plural } from "#lib/ui/format.ts";
  import { showError } from "#lib/ui/dialogs.svelte.ts";
  import { bestRun } from "./evaluation.svelte.ts";
  import TableChart from "./TableChart.svelte";
  import { exportCsv, usedColumns } from "./tables.ts";
  import { closeTable, tableOf, tableView } from "./tableView.svelte.ts";

  const open = $derived(tableView.open);
  const table = $derived(open ? tableOf(open.nodeId, open.socket) : null);
  const quality = $derived(open ? (bestRun(open.nodeId)?.quality ?? null) : null);
  const cols = $derived(table ? usedColumns(table) : []);
  let saved = $state("");

  function fmt(v: unknown): string {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("pl-PL") : num(v, Math.abs(v) < 10 ? 3 : 2);
    return String(v);
  }
  async function csv(): Promise<void> {
    if (!table) return;
    try {
      const p = await exportCsv(table);
      if (p) saved = p.split(/[\\/]/).pop() ?? p;
    } catch (e) {
      await showError("Nie udało się zapisać CSV", e);
    }
  }
  function onKey(e: KeyboardEvent): void {
    if (open && e.key === "Escape") {
      e.stopPropagation();
      closeTable();
    }
  }
  $effect(() => {
    void open;
    saved = "";
  });
</script>

<svelte:window onkeydowncapture={onKey} />

{#if open && table}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={closeTable}>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="modal" role="dialog" aria-label={table.title} tabindex="-1" onclick={(e) => e.stopPropagation()}>
      <header>
        <b>{table.title}</b>
        {#if quality === "preview"}<span class="q" title="Liczone na podglądzie — pełna rozdzielczość po chwili bezczynności">podgląd</span>{/if}
        <span class="n">{plural(table.rows.length, "wiersz", "wiersze", "wierszy")}</span>
        <button class="btn primary" onclick={csv} title="Zapisz jako CSV (Excel: średnik, przecinek dziesiętny)">
          <Icon name="download" size={12} /> CSV
        </button>
        {#if saved}<span class="ok">✓ {saved}</span>{/if}
        <button class="close" title="Zamknij (Esc)" onclick={closeTable}>✕</button>
      </header>
      {#if table.chart}
        <div class="chart"><TableChart {table} height={140} large /></div>
      {/if}
      <div class="scroll">
        <table>
          <thead>
            <tr>
              {#each cols as c (c.key)}<th>{c.label}{#if c.unit}<small> {c.unit}</small>{/if}</th>{/each}
            </tr>
          </thead>
          <tbody>
            {#each table.rows as r, n (n)}
              <tr>
                {#each cols as c (c.key)}
                  <td class:num={typeof r[c.key] === "number"}>
                    {#if c.key === "name" && r.color}<i style:background={r.color as string}></i>{/if}{fmt(r[c.key])}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 900;
    background: var(--backdrop);
    display: flex;
    align-items: center;
    justify-content: center;
    animation: fade 0.15s ease;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
  .modal {
    width: min(980px, calc(100vw - 60px));
    max-height: min(760px, calc(100vh - 60px));
    display: flex;
    flex-direction: column;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-top: 2px solid var(--port-tabela);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: 0 16px 50px rgba(0, 0, 0, 0.6);
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--line-1);
    font-size: var(--fs-sm);
  }
  header b {
    color: var(--text);
  }
  .q {
    font-size: var(--fs-xs);
    color: var(--accent);
  }
  .n {
    flex: 1;
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
  .ok {
    font-size: var(--fs-xs);
    color: var(--port-segment);
  }
  .close {
    background: none;
    border: 0;
    color: var(--text-dim-2);
    cursor: pointer;
    font-size: 0.9rem;
  }
  .close:hover {
    color: var(--text);
  }
  .chart {
    padding: 12px 16px 4px;
  }
  .scroll {
    overflow: auto;
    padding: 6px 8px 12px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--fs-xs);
  }
  th {
    position: sticky;
    top: 0;
    text-align: left;
    font-weight: 600;
    color: var(--text-dim-1);
    background: var(--bg-panel);
    padding: 6px 8px;
    border-bottom: 1px solid var(--line-2);
    white-space: nowrap;
  }
  th small {
    color: var(--text-dim-3);
    font-weight: 400;
  }
  td {
    padding: 4px 8px;
    border-bottom: 1px solid var(--line-1);
    color: var(--text);
    white-space: nowrap;
  }
  td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  td i {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 2px;
    margin-right: 6px;
  }
  tr:hover td {
    background: var(--bg-deepest);
  }
</style>
