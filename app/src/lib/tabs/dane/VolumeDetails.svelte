<script lang="ts">
  import { deleteVolume, renameVolume, type VolumeEntry } from "#lib/core/library.svelte.ts";
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import { confirmAction, promptText, showError } from "#lib/ui/dialogs.svelte.ts";
  import Icon from "#lib/ui/Icon.svelte";
  import { bytes, dims, mm, num } from "#lib/ui/format.ts";
  import SlicePreview from "./SlicePreview.svelte";
  import TagBrowser from "./TagBrowser.svelte";

  let { vol }: { vol: VolumeEntry } = $props();
  type Sub = "podglad" | "tagi" | "info";
  let sub = $state<Sub>(wsGet<Sub>("dane_detailsTab", "podglad"));

  function setSub(s: Sub): void {
    sub = s;
    wsSet("dane_detailsTab", s);
  }

  async function rename(): Promise<void> {
    const name = await promptText("Zmień nazwę wolumenu", { value: vol.name, confirmText: "Zapisz" });
    if (name && name !== vol.name) await renameVolume(vol.id, name).catch((e) => showError("Błąd", e));
  }

  async function remove(): Promise<void> {
    const ok = await confirmAction(
      "Usunąć wolumen?",
      `„${vol.name}” zniknie z biblioteki (${bytes(vol.bytesOnDisk)}). Pliki źródłowe nie są ruszane.`,
      { confirmText: "Usuń", danger: true },
    );
    if (ok) await deleteVolume(vol.id).catch((e) => showError("Błąd", e));
  }

  const info = $derived(
    [
      ["Pacjent", vol.patientName],
      ["Płeć / wiek", [vol.patientSex, vol.patientAge].filter(Boolean).join(" / ")],
      ["Badanie", vol.studyDescription],
      ["Data badania", vol.studyDate],
      ["Seria", vol.seriesNumber],
      ["Okolica", vol.bodyPart],
      ["Producent", vol.manufacturer],
      ["Wymiary", `${dims(vol.size)} wokseli`],
      ["Rozmiar woksela", mm(vol.spacing)],
      ["Zakres fizyczny", mm(vol.size.map((n, i) => n * vol.spacing[i]))],
      ["Typ danych", vol.dtype],
      ["Zakres wartości", `${num(vol.stats.min, 0)} … ${num(vol.stats.max, 0)}`],
      ["Poziomy piramidy", String(vol.levels)],
      ["Na dysku", bytes(vol.bytesOnDisk)],
      ["Źródło", vol.source === "dicom" ? `DICOM, ${vol.nFiles ?? "?"} plików` : vol.source.toUpperCase()],
      ["Ścieżka źródła", vol.sourcePath ?? (vol.anonymized ? "ukryta (anonimizacja)" : "")],
      ["Import", `${vol.createdAt.replace("T", " ")} · ${num(vol.importSeconds, 2)} s`],
    ].filter(([, v]) => v) as [string, string][],
  );
</script>

<div class="details">
  <header>
    <div class="title">
      <span class="name">{vol.name}</span>
      <div class="badges">
        {#if vol.modality}<span class="badge">{vol.modality}</span>{/if}
        {#if vol.anonymized}<span class="badge anon">zanonimizowany</span>{/if}
      </div>
    </div>
    <button class="icon-btn" title="Zmień nazwę" onclick={rename}><Icon name="edit" /></button>
    <button class="icon-btn danger" title="Usuń z biblioteki" onclick={remove}><Icon name="trash" /></button>
  </header>

  {#each vol.warnings as w, n (n)}
    <div class="warn"><Icon name="alert" size={12} /> {w}</div>
  {/each}

  <nav>
    <button class="seg" class:active={sub === "podglad"} onclick={() => setSub("podglad")}>Podgląd</button>
    <button class="seg" class:active={sub === "info"} onclick={() => setSub("info")}>Informacje</button>
    <button class="seg" class:active={sub === "tagi"} onclick={() => setSub("tagi")}>Tagi DICOM</button>
  </nav>

  {#if sub === "podglad"}
    <SlicePreview {vol} />
  {:else if sub === "info"}
    <dl>
      {#each info as [k, v] (k)}
        <dt>{k}</dt>
        <dd>{v}</dd>
      {/each}
    </dl>
  {:else}
    <TagBrowser vid={vol.id} />
  {/if}
</div>

<style>
  .details {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .title {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .name {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-strong);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .badges {
    display: flex;
    gap: 6px;
  }
  .badge {
    font-size: 0.6rem;
    font-weight: 600;
    color: var(--port-wolumen);
    border: 1px solid currentColor;
    border-radius: 4px;
    padding: 1px 6px;
  }
  .badge.anon {
    color: var(--ok);
  }
  .icon-btn {
    display: flex;
    padding: 6px;
    background: none;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-dim-2);
    cursor: pointer;
  }
  .icon-btn:hover {
    color: var(--text);
    border-color: var(--line-2);
  }
  .icon-btn.danger:hover {
    color: var(--danger);
    border-color: var(--danger);
  }
  .warn {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-xs);
    color: var(--port-punkty);
  }
  nav {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--line-1);
    padding-bottom: 8px;
  }
  .seg {
    padding: 4px 12px;
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.04em;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-dim-3);
    cursor: pointer;
  }
  .seg:hover:not(.active) {
    background: var(--hover);
    color: var(--text-dim-1);
  }
  .seg.active {
    background: var(--accent-a10);
    border-color: var(--accent-a30);
    color: var(--accent);
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 18px;
    font-size: var(--fs-sm);
    overflow-y: auto;
    align-content: start;
  }
  dt {
    color: var(--text-dim-3);
  }
  dd {
    color: var(--text);
    word-break: break-all;
    -webkit-user-select: text;
    user-select: text;
  }
</style>
