<script lang="ts">
  import { libraryLoaded, libraryVolumes, thumbUrl } from "#lib/core/library.svelte.ts";
  import { inTauri, pickImportPaths } from "#lib/core/tauri.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { bytes, dims } from "#lib/ui/format.ts";
  import ImportDialog from "./ImportDialog.svelte";
  import { isScanning, scanPaths } from "./importFlow.svelte.ts";
  import VolumeDetails from "./VolumeDetails.svelte";

  const volumes = $derived(libraryVolumes());
  let selectedId = $state(wsGet<string>("dane_selectedVolume", ""));
  const selected = $derived(volumes.find((v) => v.id === selectedId) ?? volumes[0]);

  function select(id: string): void {
    selectedId = id;
    wsSet("dane_selectedVolume", id);
  }

  const importFrom = async (kind: "folders" | "files") => scanPaths(await pickImportPaths(kind));
</script>

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

    {#if libraryLoaded() && !volumes.length}
      <div class="empty">
        <Icon name="cube" size={34} />
        <span>Biblioteka jest pusta</span>
        <small>Wybierz folder z seriami DICOM albo pliki NIfTI / NRRD / MHA (mesh: STL / OBJ / PLY) — możesz też upuścić je na okno.</small>
      </div>
    {:else}
      <ul>
        {#each volumes as v (v.id)}
          <li>
            <button class="card" class:active={selected?.id === v.id} onclick={() => select(v.id)}>
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
