<script lang="ts">
  import { libraryLoaded, libraryVolumes, thumbUrl } from "#lib/core/library.svelte.ts";
  import { inTauri, pickImportPaths } from "#lib/core/tauri.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { bytes, dims } from "#lib/ui/format.ts";
  import ImportDialog from "./ImportDialog.svelte";
  import { isScanning, scanPaths } from "./importFlow.svelte.ts";
  import VolumeDetails from "./VolumeDetails.svelte";
  import { confirmAction, promptText } from "#lib/ui/dialogs.svelte.ts";
  import {
    ALL,
    LOOSE,
    addFolder,
    claimNew,
    danePanel,
    folderOf,
    inFolder,
    moveToFolder,
    openFolder,
    removeFolder,
    renameFolder,
  } from "./folders.svelte.ts";

  const all = $derived(libraryVolumes());
  $effect(() => claimNew(all.map((v) => v.id)));
  const volumes = $derived(all.filter((v) => inFolder(v.id, danePanel.current)));
  const count = (f: string) => all.filter((v) => inFolder(v.id, f)).length;
  const folderRows = $derived([
    { id: ALL, name: "Wszystkie", fixed: true },
    ...danePanel.folders.map((f) => ({ ...f, fixed: false })),
    ...(danePanel.folders.length ? [{ id: LOOSE, name: "Bez folderu", fixed: true }] : []),
  ]);

  async function newFolder(): Promise<void> {
    const name = (await promptText("Nowy folder", { label: "Nazwa", confirmText: "Utwórz" }))?.trim();
    if (name) addFolder(name);
  }
  async function rename(id: string, name: string): Promise<void> {
    const n = (await promptText("Zmień nazwę folderu", { value: name, confirmText: "Zapisz" }))?.trim();
    if (n) renameFolder(id, n);
  }
  async function remove(id: string, name: string): Promise<void> {
    if (await confirmAction(`Usunąć folder „${name}”?`, "Dane zostaną w bibliotece (Bez folderu).", { confirmText: "Usuń", danger: true }))
      removeFolder(id);
  }

  // drag a card onto a folder (Pointer Events; a click below 5 px of movement stays a click)
  let drag = $state<{ id: string; x0: number; y0: number; x: number; y: number; on: boolean; over: string | null } | null>(null);
  function onCardDown(e: PointerEvent, id: string): void {
    if (e.button !== 0) return;
    drag = { id, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, on: false, over: null };
  }
  function onWinMove(e: PointerEvent): void {
    if (!drag) return;
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (!drag.on && Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 5) drag.on = true;
    if (drag.on) {
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-folder]");
      drag.over = el?.dataset.folder ?? null;
    }
  }
  function onWinUp(): void {
    if (drag?.on && drag.over !== null && drag.over !== ALL) moveToFolder(drag.id, drag.over);
    drag = null;
  }
  const dragged = $derived(drag?.on ? all.find((v) => v.id === drag!.id) : undefined);
  let selectedId = $state(wsGet<string>("dane_selectedVolume", ""));
  const selected = $derived(volumes.find((v) => v.id === selectedId) ?? volumes[0]);

  function select(id: string): void {
    selectedId = id;
    wsSet("dane_selectedVolume", id);
  }

  const importFrom = async (kind: "folders" | "files") => scanPaths(await pickImportPaths(kind));
</script>

<svelte:window onpointermove={onWinMove} onpointerup={onWinUp} />

<div class="dane">
  <aside>
    <div class="toolbar">
      <button class="btn primary" disabled={!inTauri() || isScanning()} onclick={() => importFrom("folders")}>
        <Icon name="folderIn" /> Folder…
      </button>
      <button class="btn" disabled={!inTauri() || isScanning()} onclick={() => importFrom("files")}>
        Pliki…
      </button>
      {#if isScanning()}<span class="scanning">Skanowanie…</span>{/if}
    </div>

    <div class="folders">
      {#each folderRows as f (f.id)}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div
          class="frow"
          class:active={danePanel.current === f.id}
          class:drop={drag?.on && drag.over === f.id && f.id !== ALL && folderOf(drag.id) !== f.id}
          data-folder={f.id}
          onclick={() => openFolder(f.id)}
          ondblclick={() => !f.fixed && rename(f.id, f.name)}
          title={f.fixed ? "" : "Dwuklik: zmień nazwę · przeciągnij tu dane"}
        >
          {#if f.id === ALL}
            <Icon name="layers" size={14} />
          {:else}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h6l2 2h10v11H3z" /></svg>
          {/if}
          <span class="fname">{f.name}</span>
          <small>{count(f.id)}</small>
          {#if !f.fixed}
            <button class="fdel" title="Usuń folder" onclick={(e) => (e.stopPropagation(), remove(f.id, f.name))}>
              <Icon name="trash" size={12} />
            </button>
          {/if}
        </div>
      {/each}
      <button class="frow add" onclick={newFolder} title="Nowy folder"><Icon name="plus" size={14} /><span class="fname">Folder</span></button>
    </div>

    {#if libraryLoaded() && !all.length}
      <div class="empty">
        <Icon name="cube" size={34} />
        <span>Biblioteka jest pusta</span>
        <small>Wybierz folder z seriami DICOM albo pliki NIfTI / NRRD / MHA (mesh: STL / OBJ / PLY) — możesz też upuścić je na okno.</small>
      </div>
    {:else if !volumes.length}
      <div class="fempty">Pusty folder — przeciągnij tu dane albo zaimportuj, gdy jest otwarty.</div>
    {:else}
      <ul>
        {#each volumes as v (v.id)}
          <li>
            <button
              class="card"
              class:active={selected?.id === v.id}
              class:ghost={drag?.on && drag.id === v.id}
              onpointerdown={(e) => onCardDown(e, v.id)}
              onclick={() => !drag?.on && select(v.id)}
            >
              <img src={thumbUrl(v.id)} alt="" loading="lazy" decoding="async" />
              <div class="meta">
                <span class="name">{v.name}</span>
                <span class="sub">
                  {#if v.modality}<b>{v.modality}</b>{/if}
                  {dims(v.size)}
                </span>
                <span class="sub">
                  {bytes(v.bytesOnDisk)}
                  {#if v.warnings.length}<span class="w" title={v.warnings.join("\n")}><Icon name="alert" size={11} /></span>{/if}
                </span>
              </div>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  {#if selected}
    {#key selected.id}
      <VolumeDetails vol={selected} />
    {/key}
  {/if}
</div>

{#if dragged && drag}
  <div class="dragchip" style:left="{drag.x + 12}px" style:top="{drag.y + 8}px">
    <img src={thumbUrl(dragged.id)} alt="" />{dragged.name}
  </div>
{/if}

<ImportDialog />

<style>
  .dane {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
  }
  aside {
    width: 300px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 12px;
    border-right: 1px solid var(--line-1);
    background: var(--bg-panel-2);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .scanning {
    font-size: var(--fs-xs);
    color: var(--accent);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.4;
    }
  }
  .empty {
    margin-top: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    text-align: center;
    color: var(--text-dim-4);
  }
  .empty span {
    font-size: var(--fs-md);
    color: var(--text-dim-3);
  }
  .empty small {
    font-size: var(--fs-xs);
    line-height: 1.6;
  }
  .folders {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--line-1);
  }
  .frow {
    display: flex;
    align-items: center;
    gap: 7px;
    height: 28px;
    padding: 0 6px;
    font-size: var(--fs-sm);
    color: var(--text-dim-2);
    background: none;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
    text-align: left;
  }
  .frow:hover {
    background: var(--bg-deep);
  }
  .frow.active {
    color: var(--accent);
    background: var(--accent-a10);
  }
  .frow.drop {
    border-color: var(--accent);
    border-style: dashed;
  }
  .frow.add {
    color: var(--text-dim-4);
  }
  .fname {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .frow small {
    font-size: var(--fs-xs);
    color: var(--text-dim-4);
  }
  .fdel {
    display: none;
    padding: 2px;
    background: none;
    border: none;
    color: var(--text-dim-4);
    cursor: pointer;
  }
  .frow:hover .fdel {
    display: flex;
  }
  .fdel:hover {
    color: var(--danger, var(--text));
  }
  .fempty {
    padding: 14px 6px;
    font-size: var(--fs-xs);
    color: var(--text-dim-4);
    text-align: center;
  }
  .card.ghost {
    opacity: 0.4;
  }
  .dragchip {
    position: fixed;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px 4px 4px;
    font-size: var(--fs-xs);
    color: var(--text);
    background: var(--bg-panel);
    border: 1px solid var(--accent-a40);
    border-radius: var(--radius-sm);
    pointer-events: none;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
  }
  .dragchip img {
    width: 24px;
    height: 24px;
  }
  ul {
    list-style: none;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .card {
    width: 100%;
    display: flex;
    gap: 10px;
    padding: 6px;
    text-align: left;
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: border-color var(--t-fast), background var(--t-fast);
  }
  .card:hover {
    border-color: var(--line-3);
  }
  .card.active {
    border-color: var(--accent-a40);
    background: var(--accent-a10);
  }
  img {
    width: 56px;
    height: 56px;
    object-fit: contain;
    background: #000;
    border-radius: 4px;
    flex-shrink: 0;
  }
  .meta {
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 3px;
  }
  .name {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card.active .name {
    color: var(--accent);
  }
  .sub {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--text-dim-3);
  }
  .sub b {
    color: var(--port-wolumen);
    font-weight: 600;
  }
  .w {
    display: flex;
    color: var(--port-punkty);
  }
</style>
