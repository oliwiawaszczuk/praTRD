<script lang="ts">
  import { getSetting } from "#lib/core/appSettings.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { bytes, dims, mm } from "#lib/ui/format.ts";
  import { closeScan, importSelected, pendingScan } from "./importFlow.svelte.ts";

  const scan = $derived(pendingScan());
  let selected = $state<Set<number>>(new Set());
  let anonymize = $state(true);

  // New scan → preselect everything not imported yet; anonymization from global setting.
  $effect(() => {
    if (!scan) return;
    selected = new Set(scan.candidates.filter((c) => !c.alreadyImported).map((c) => c.id));
    anonymize = getSetting("anonymizeOnImport", true);
  });

  const total = $derived(
    scan ? scan.candidates.filter((c) => selected.has(c.id)).reduce((s, c) => s + c.rawBytes, 0) : 0,
  );

  function toggle(id: number): void {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  function onKey(e: KeyboardEvent): void {
    if (scan && e.key === "Escape") closeScan();
  }
</script>

<svelte:window onkeydown={onKey} />

{#if scan}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={closeScan}>
    <div class="modal" role="dialog" tabindex="-1" aria-label="Import serii" onclick={(e) => e.stopPropagation()}>
      <header>
        <h2>Znalezione serie</h2>
        <span class="count">{scan.candidates.length}</span>
      </header>

      <ul>
        {#each scan.candidates as c (c.id)}
          <li class:dim={c.alreadyImported && !selected.has(c.id)}>
            <label>
              <input type="checkbox" checked={selected.has(c.id)} onchange={() => toggle(c.id)} />
              <div class="body">
                <div class="row1">
                  <span class="badge">{c.modality || c.kind.toUpperCase()}</span>
                  <span class="name">{c.name}</span>
                  {#if c.alreadyImported}<span class="tag">już w bibliotece</span>{/if}
                </div>
                <div class="row2">
                  <span>{dims(c.size)}</span>
                  <span>{mm(c.spacing)}</span>
                  <span>{c.dtype}</span>
                  <span>{bytes(c.rawBytes)}</span>
                  {#if c.nFiles && c.nFiles > 1}<span>{c.nFiles} plików</span>{/if}
                </div>
                {#if c.patientName || c.studyDescription || c.studyDate}
                  <div class="row2 muted">
                    {#if c.patientName}<span>{c.patientName}</span>{/if}
                    {#if c.studyDescription}<span>{c.studyDescription}</span>{/if}
                    {#if c.studyDate}<span>{c.studyDate}</span>{/if}
                  </div>
                {/if}
                {#each c.warnings as w, n (n)}
                  <div class="warn"><Icon name="alert" size={12} /> {w}</div>
                {/each}
              </div>
            </label>
          </li>
        {/each}
      </ul>

      <footer>
        <label class="anon">
          <input type="checkbox" bind:checked={anonymize} />
          Anonimizuj (usuń dane osobowe z tagów i opisu)
        </label>
        <span class="spacer"></span>
        <span class="total">{selected.size} serii · {bytes(total)}</span>
        <button class="btn" onclick={closeScan}>Anuluj</button>
        <button
          class="btn primary"
          disabled={!selected.size}
          onclick={() => importSelected([...selected], anonymize)}
        >
          Importuj
        </button>
      </footer>
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
  }
  .modal {
    width: min(760px, calc(100vw - 48px));
    max-height: calc(100vh - 80px);
    display: flex;
    flex-direction: column;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
  header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 16px 18px 10px;
  }
  h2 {
    font-size: var(--fs-lg);
    font-weight: 600;
    color: var(--text-strong);
  }
  .count {
    font-size: var(--fs-xs);
    color: var(--accent);
    background: var(--accent-a10);
    border: 1px solid var(--accent-a25);
    border-radius: 10px;
    padding: 1px 8px;
  }
  ul {
    list-style: none;
    overflow-y: auto;
    padding: 0 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  li {
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    background: var(--bg-deep);
  }
  li.dim {
    opacity: 0.55;
  }
  label {
    display: flex;
    gap: 10px;
    padding: 9px 11px;
    cursor: pointer;
  }
  input[type="checkbox"] {
    accent-color: var(--accent);
    margin-top: 2px;
  }
  .body {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .row1 {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .badge {
    font-size: 0.6rem;
    font-weight: 600;
    color: var(--port-wolumen);
    border: 1px solid currentColor;
    border-radius: 4px;
    padding: 0 5px;
  }
  .name {
    font-size: var(--fs-md);
    color: var(--text-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tag {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
  .row2 {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
  }
  .muted {
    color: var(--text-dim-3);
  }
  .warn {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--port-punkty);
  }
  footer {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    border-top: 1px solid var(--line-1);
    margin-top: 10px;
  }
  .anon {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 0;
    font-size: var(--fs-sm);
    color: var(--text-dim-1);
  }
  .spacer {
    flex: 1;
  }
  .total {
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
</style>
