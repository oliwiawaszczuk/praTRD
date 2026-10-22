<script lang="ts">
  import Icon from "#lib/ui/Icon.svelte";
  import { activeWorkspaceId, switchWorkspace, workspaces } from "#lib/core/workspace.svelte.ts";
  import {
    deleteWorkspaceFlow,
    exportWorkspaceFlow,
    importWorkspaceFlow,
    newWorkspaceFlow,
    renameWorkspaceFlow,
  } from "#lib/core/workspaceActions.ts";
  import { inTauri } from "#lib/core/tauri.ts";

  const list = $derived(workspaces());
  const active = $derived(activeWorkspaceId());
  const fmt = new Intl.DateTimeFormat("pl-PL", { dateStyle: "medium" });
</script>

<div class="toolbar">
  <button class="btn primary" onclick={newWorkspaceFlow}><Icon name="plus" /> Nowy</button>
  <button class="btn" onclick={importWorkspaceFlow} disabled={!inTauri()}>
    <Icon name="folderIn" /> Importuj…
  </button>
</div>

<ul>
  {#each list as ws (ws.id)}
    <li class:active={ws.id === active}>
      <button class="name" onclick={() => ws.id !== active && switchWorkspace(ws.id)} title="Przełącz">
        <span class="dot"></span>
        <span class="label">{ws.name}</span>
        <span class="date">{fmt.format(new Date(ws.createdAt))}</span>
      </button>
      <div class="actions">
        <button class="icon-btn" title="Zmień nazwę" onclick={() => renameWorkspaceFlow(ws)}>
          <Icon name="edit" />
        </button>
        <button
          class="icon-btn"
          title="Eksportuj…"
          disabled={!inTauri()}
          onclick={() => exportWorkspaceFlow(ws)}
        >
          <Icon name="folderOut" />
        </button>
        <button
          class="icon-btn danger"
          title="Usuń"
          disabled={list.length <= 1}
          onclick={() => deleteWorkspaceFlow(ws)}
        >
          <Icon name="trash" />
        </button>
      </div>
    </li>
  {/each}
</ul>

<style>
  .toolbar {
    display: flex;
    gap: 8px;
  }
  ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  li {
    display: flex;
    align-items: center;
    gap: 6px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    padding: 2px 4px 2px 0;
    transition: background var(--t-fast), border-color var(--t-fast);
  }
  li:hover {
    background: var(--hover);
  }
  li.active {
    background: var(--accent-a10);
    border-color: var(--accent-a25);
  }
  .name {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 10px;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--line-3);
    flex-shrink: 0;
  }
  li.active .dot {
    background: var(--accent);
    box-shadow: 0 0 6px var(--accent-a70);
  }
  .label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--fs-md);
    color: var(--text);
  }
  li.active .label {
    color: var(--accent);
  }
  .date {
    font-size: var(--fs-xs);
    color: var(--text-dim-4);
  }
  .actions {
    display: flex;
    gap: 2px;
    opacity: 0;
    transition: opacity var(--t-fast);
  }
  li:hover .actions,
  li:focus-within .actions {
    opacity: 1;
  }
  .icon-btn {
    display: flex;
    padding: 5px;
    background: none;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-dim-2);
    cursor: pointer;
  }
  .icon-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--line-2);
  }
  .icon-btn.danger:hover:not(:disabled) {
    color: var(--danger);
    border-color: var(--danger);
  }
  .icon-btn:disabled {
    opacity: 0.3;
    cursor: default;
  }
</style>
