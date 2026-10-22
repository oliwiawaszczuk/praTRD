<script lang="ts">
  import { getSetting, setSetting } from "#lib/core/appSettings.svelte.ts";
  import { allJobs } from "#lib/core/events.svelte.ts";
  import { confirmAction, promptText, showError } from "#lib/ui/dialogs.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { evaluateFull, runs } from "./evaluation.svelte.ts";
  import { createGraph, deleteGraph, graph, openGraph, redo, renameGraph, undo } from "./store.svelte.ts";

  let {
    onfit,
    maximized = false,
    onmax,
  }: { running: string; onfit: () => void; maximized?: boolean; onmax?: () => void } = $props();

  const job = (id: string) => allJobs().find((j) => j.id === id);
  const previewState = $derived(job(runs.previewJob)?.state);
  const fullJob = $derived(job(runs.fullJob));
  const fullDone = $derived(graph.doc.display ? runs.full[graph.doc.display]?.state === "done" : false);
  const autoFull = $derived(getSetting("graphAutoFull", true));

  async function onSelect(v: string): Promise<void> {
    try {
      if (v === "__new") {
        const name = await promptText("Nowy graf", { label: "Nazwa", confirmText: "Utwórz" });
        if (name) await createGraph(name);
      } else if (v === "__rename") {
        const cur = graph.list.find((g) => g.id === graph.activeId);
        const name = await promptText("Zmień nazwę grafu", { value: cur?.name ?? "", confirmText: "Zapisz" });
        if (name) await renameGraph(graph.activeId, name);
      } else if (v === "__delete") {
        const cur = graph.list.find((g) => g.id === graph.activeId);
        if (await confirmAction("Usunąć graf?", `„${cur?.name}” zostanie usunięty.`, { confirmText: "Usuń", danger: true }))
          await deleteGraph(graph.activeId);
      } else await openGraph(v);
    } catch (e) {
      await showError("Błąd", e);
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="bar" onpointerdown={(e) => e.stopPropagation()} onwheel={(e) => e.stopPropagation()}>
  <select
    class="sel"
    value={graph.activeId}
    onchange={(e) => {
      const v = e.currentTarget.value;
      e.currentTarget.value = graph.activeId;
      void onSelect(v);
    }}
  >
    {#each graph.list as g (g.id)}<option value={g.id}>{g.name}</option>{/each}
    <option disabled>──────────</option>
    <option value="__new">+ Nowy graf…</option>
    <option value="__rename">Zmień nazwę…</option>
    {#if graph.list.length > 1}<option value="__delete">Usuń graf…</option>{/if}
  </select>
  <button class="ib" title="Cofnij (⌘Z)" disabled={!graph.canUndo} onclick={undo}><Icon name="undo" size={13} /></button>
  <button class="ib" title="Ponów (⇧⌘Z)" disabled={!graph.canRedo} onclick={redo}><Icon name="redo" size={13} /></button>
  <button class="ib" title="Dopasuj widok (F)" onclick={onfit}>F</button>
  {#if onmax}
    <button class="ib" class:on={maximized} title="Graf na cały ekran (Ctrl+Spacja)" onclick={onmax}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        {#if maximized}<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />{:else}<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />{/if}
      </svg>
    </button>
  {/if}
  <span class="sep"></span>
  <span class="st" class:busy={previewState === "running"}>
    podgląd {previewState === "running" ? "liczy…" : previewState === "error" ? "błąd" : "✓"}
  </span>
  {#if graph.doc.display}
    <span class="st" class:busy={fullJob?.state === "running"}>
      pełna {fullJob?.state === "running" ? `${Math.round(fullJob.progress * 100)}%` : fullDone ? "✓" : "—"}
    </span>
    <button class="ib play" title="Przelicz w pełnej rozdzielczości (wyświetlany node i pomiary)" onclick={() => evaluateFull()}>
      <Icon name="play" size={11} />
    </button>
  {/if}
  <label class="auto" title="Po chwili bezczynności automatycznie licz pełną rozdzielczość">
    <input type="checkbox" checked={autoFull} onchange={(e) => setSetting("graphAutoFull", e.currentTarget.checked)} />
    auto
  </label>
</div>

<style>
  .bar {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 6px;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
    font-size: var(--fs-xs);
  }
  .sel {
    max-width: 160px;
    padding: 3px 6px;
    font-size: var(--fs-xs);
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: 4px;
    color: var(--text);
  }
  .ib {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 24px;
    height: 22px;
    padding: 0 5px;
    font-size: 0.64rem;
    font-weight: 600;
    background: none;
    border: 1px solid transparent;
    border-radius: 4px;
    color: var(--text-dim-2);
    cursor: pointer;
  }
  .ib:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--line-2);
  }
  .ib:disabled {
    opacity: 0.3;
  }
  .play,
  .ib.on {
    color: var(--accent);
  }
  .sep {
    width: 1px;
    height: 16px;
    background: var(--line-2);
    margin: 0 4px;
  }
  .st {
    color: var(--text-dim-3);
    white-space: nowrap;
  }
  .st.busy {
    color: var(--accent);
  }
  .auto {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-left: 4px;
    color: var(--text-dim-3);
  }
  .auto input {
    accent-color: var(--accent);
  }
</style>
