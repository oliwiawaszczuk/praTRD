<script lang="ts">
  import { closeDialog, currentDialog } from "./dialogs.svelte";

  const d = $derived(currentDialog());
  let text = $state("");
  let input = $state<HTMLInputElement>();

  $effect(() => {
    if (d?.kind === "prompt") {
      text = d.value;
      queueMicrotask(() => input?.select());
    }
  });

  function cancel(): void {
    if (!d) return;
    if (d.kind === "prompt") d.resolve(null);
    else if (d.kind === "confirm") d.resolve(false);
    else d.resolve();
    closeDialog();
  }

  function accept(): void {
    if (!d) return;
    if (d.kind === "prompt") {
      if (!text.trim()) return;
      d.resolve(text.trim());
    } else if (d.kind === "confirm") d.resolve(true);
    else d.resolve();
    closeDialog();
  }

  function onKey(e: KeyboardEvent): void {
    if (!d) return;
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    } else if (e.key === "Enter") {
      e.preventDefault();
      accept();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

{#if d}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="backdrop" onclick={cancel}>
    <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label={d.title} onclick={(e) => e.stopPropagation()}>
      <h2 class:danger={d.kind === "alert" && d.error}>{d.title}</h2>
      {#if d.kind === "prompt"}
        {#if d.label}<span class="label">{d.label}</span>{/if}
        <input class="input" bind:this={input} bind:value={text} spellcheck="false" />
      {:else}
        <p>{d.message}</p>
      {/if}
      <div class="actions">
        {#if d.kind !== "alert"}
          <button class="btn" onclick={cancel}>Anuluj</button>
        {/if}
        <button
          class="btn"
          class:primary={d.kind !== "confirm" || !d.danger}
          class:danger={d.kind === "confirm" && d.danger}
          onclick={accept}
        >
          {d.kind === "alert" ? "OK" : d.confirmText}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: var(--backdrop);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    animation: fade 0.12s ease;
  }
  .modal {
    width: min(420px, calc(100vw - 32px));
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    padding: 18px 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
  h2 {
    font-size: var(--fs-lg);
    font-weight: 600;
    color: var(--text-strong);
  }
  h2.danger {
    color: var(--danger);
  }
  p {
    font-size: var(--fs-md);
    color: var(--text-dim-1);
    line-height: 1.6;
    white-space: pre-wrap;
    -webkit-user-select: text;
    user-select: text;
  }
  .label {
    font-size: var(--fs-xs);
    color: var(--text-dim-2);
    margin-bottom: -6px;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 4px;
  }
  @keyframes fade {
    from {
      opacity: 0;
    }
  }
</style>
