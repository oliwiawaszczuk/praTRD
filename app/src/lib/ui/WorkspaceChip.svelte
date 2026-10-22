<script lang="ts">
  import Icon from "./Icon.svelte";
  import {
    activeWorkspace,
    activeWorkspaceId,
    switchWorkspace,
    workspaces,
  } from "#lib/core/workspace.svelte.ts";
  import { newWorkspaceFlow } from "#lib/core/workspaceActions.ts";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  const current = $derived(activeWorkspace());
  const activeId = $derived(activeWorkspaceId());
  let root = $state<HTMLDivElement>();

  function onPointerDown(e: PointerEvent): void {
    if (open && root && !root.contains(e.target as Node)) open = false;
  }
  function onKey(e: KeyboardEvent): void {
    if (open && e.key === "Escape") open = false;
  }
</script>

<svelte:window onpointerdown={onPointerDown} onkeydown={onKey} />

<div class="chip-wrap" bind:this={root}>
  <button class="chip" class:open onclick={() => (open = !open)} title="Workspace">
    <Icon name="layers" size={13} />
    <span class="name">{current?.name ?? "—"}</span>
    <span class="caret">▾</span>
  </button>
  {#if open}
    <div class="pop" role="menu">
      {#each workspaces() as ws (ws.id)}
        <button
          role="menuitem"
          class="item"
          class:active={ws.id === activeId}
          onclick={() => {
            open = false;
            if (ws.id !== activeId) switchWorkspace(ws.id);
          }}
        >
          {#if ws.id === activeId}<Icon name="check" size={12} />{:else}<span class="pad"></span>{/if}
          <span class="n">{ws.name}</span>
        </button>
      {/each}
      <div class="sep"></div>
      <button
        role="menuitem"
        class="item"
        onclick={() => {
          open = false;
          newWorkspaceFlow();
        }}
      >
        <Icon name="plus" size={12} /> <span class="n">Nowy workspace…</span>
      </button>
    </div>
  {/if}
</div>

<style>
  .chip-wrap {
    position: relative;
    align-self: center;
    margin-bottom: 6px;
  }
  .chip {
    display: flex;
    align-items: center;
    gap: 7px;
    max-width: 260px;
    padding: 4px 10px;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-dim-1);
    background: var(--shade);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: color var(--t-fast), border-color var(--t-fast);
  }
  .chip:hover,
  .chip.open {
    color: var(--accent);
    border-color: var(--accent-a30);
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .caret {
    font-size: 0.6rem;
    opacity: 0.6;
  }
  .pop {
    position: absolute;
    right: 0;
    top: calc(100% + 6px);
    z-index: 500;
    min-width: 220px;
    max-height: 60vh;
    overflow-y: auto;
    padding: 4px;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  }
  .item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 9px;
    font-size: var(--fs-sm);
    text-align: left;
    color: var(--text-dim-1);
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .item:hover {
    background: var(--hover);
    color: var(--text);
  }
  .item.active {
    color: var(--accent);
  }
  .pad {
    width: 12px;
  }
  .n {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sep {
    height: 1px;
    margin: 4px 2px;
    background: var(--line-1);
  }
</style>
