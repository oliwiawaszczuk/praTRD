<script lang="ts">
  import { fly } from "svelte/transition";
  import Icon, { type IconName } from "./Icon.svelte";
  import { dismiss, toasts } from "./toast.svelte.ts";
</script>

<div class="toasts">
  {#each toasts() as t (t.id)}
    <button
      class="toast"
      class:act={!!t.action}
      class:err={t.error}
      transition:fly={{ y: 12, duration: 160 }}
      onclick={() => {
        t.action?.();
        dismiss(t.id);
      }}
    >
      {#if t.icon}<Icon name={t.icon as IconName} size={14} />{/if}
      <span>{t.text}</span>
      {#if t.action}<span class="go">›</span>{/if}
    </button>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    left: 50%;
    bottom: 22px;
    transform: translateX(-50%);
    z-index: 1100;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    pointer-events: none;
  }
  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    font: inherit;
    font-size: var(--fs-sm);
    color: var(--text-strong);
    background: var(--bg-panel);
    border: 1px solid var(--accent-a30);
    border-radius: 20px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    cursor: default;
  }
  .toast :global(svg) {
    color: var(--accent);
  }
  .toast.act {
    cursor: pointer;
  }
  .toast.act:hover {
    border-color: var(--accent);
  }
  .toast.err {
    border-color: var(--danger);
  }
  .go {
    color: var(--accent);
    font-weight: 700;
  }
</style>
