<script lang="ts">
  // Notatki — free-text notes, global (not per workspace). List + search with arrow-key
  // navigation; a row opens the full editor. The pin puts a note into the floating note pad
  // (FloatingNotePad, over every tab), where Cmd/Ctrl+click on values in the app lands.
  import { onMount, tick } from "svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import { confirmAction } from "#lib/ui/dialogs.svelte.ts";
  import { padState, pinnedNoteId, setPadState, setPinnedNote } from "#lib/core/notePad.svelte.ts";
  import {
    createNote,
    deleteNote,
    flushNote,
    getNote,
    loadNotes,
    notes,
    notesLoaded,
    scheduleSaveNote,
    type NoteMeta,
  } from "./notes.svelte.ts";

  let search = $state("");
  let active = $state(-1);
  let openId = $state<string | null>(null);
  let text = $state("");
  let loading = $state(false);
  let listEl = $state<HTMLDivElement>();
  let editor = $state<HTMLTextAreaElement>();

  const filtered = $derived.by(() => {
    const q = search.trim().toLowerCase();
    const all = [...notes()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    return q ? all.filter((n) => n.title.toLowerCase().includes(q) || n.preview.toLowerCase().includes(q)) : all;
  });
  $effect(() => {
    if (active >= filtered.length) active = filtered.length - 1;
  });

  onMount(() => {
    if (!notesLoaded()) void loadNotes();
  });

  function onSearchKey(e: KeyboardEvent): void {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!filtered.length) return;
      active = e.key === "ArrowDown" ? Math.min(filtered.length - 1, active + 1) : Math.max(0, active - 1);
      void tick().then(() => listEl?.querySelector(".row.active")?.scrollIntoView({ block: "nearest" }));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const n = filtered[Math.max(0, active)];
      if (n) void open(n.id);
    } else if (e.key === "Escape") {
      search = "";
      active = -1;
    }
  }

  async function open(id: string): Promise<void> {
    await flushNote();
    openId = id;
    loading = true;
    text = await getNote(id);
    loading = false;
    await tick();
    editor?.focus();
  }
  async function back(): Promise<void> {
    await flushNote();
    openId = null;
  }
  async function create(): Promise<void> {
    const n = await createNote();
    await open(n.id);
  }
  async function remove(n: NoteMeta, e: MouseEvent): Promise<void> {
    e.stopPropagation();
    if (!(await confirmAction("Usunąć notatkę?", `„${n.title}” — tej operacji nie można cofnąć.`, { confirmText: "Usuń", danger: true }))) return;
    if (pinnedNoteId() === n.id) setPinnedNote(null);
    if (openId === n.id) openId = null;
    await deleteNote(n.id);
  }
  function togglePin(id: string, e?: MouseEvent): void {
    e?.stopPropagation();
    if (pinnedNoteId() === id) setPinnedNote(null);
    else {
      setPinnedNote(id);
      if (padState() === "min") setPadState("medium");
    }
  }
  const date = (iso: string) => {
    try {
      return new Date(iso).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
    } catch {
      return "";
    }
  };
  const openMeta = $derived(notes().find((n) => n.id === openId));
</script>

<div class="notatki">
  {#if !openId}
    <div class="bar">
      <span class="sicon"><Icon name="search" size={14} /></span>
      <input class="search" placeholder="Szukaj w notatkach…" bind:value={search} onkeydown={onSearchKey} />
      <button class="btn primary" onclick={create}><Icon name="plus" size={12} /> Nowa notatka</button>
    </div>
    <div class="list" bind:this={listEl}>
      {#if notesLoaded() && !filtered.length}
        <div class="empty">
          <Icon name="note" size={34} />
          <span>{notes().length ? "Brak wyników" : "Brak notatek — utwórz pierwszą"}</span>
        </div>
      {/if}
      {#each filtered as n, i (n.id)}
        <div
          class="row"
          class:active={i === active}
          class:pinned={pinnedNoteId() === n.id}
          role="button"
          tabindex="0"
          onclick={() => open(n.id)}
          onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open(n.id))}
          onpointerenter={() => (active = i)}
        >
          <div class="head">
            <span class="title">{n.title || "(bez tytułu)"}</span>
            <span class="date">{date(n.updatedAt)}</span>
          </div>
          {#if n.preview}<div class="preview">{n.preview}</div>{/if}
          <div class="acts">
            <button class="ib" class:on={pinnedNoteId() === n.id} title={pinnedNoteId() === n.id ? "Odepnij" : "Przypnij — notatnik nad całą aplikacją"} onclick={(e) => togglePin(n.id, e)}>
              <Icon name="pin" size={14} />
            </button>
            <button class="ib del" title="Usuń" onclick={(e) => remove(n, e)}><Icon name="trash" size={14} /></button>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="detail">
      <div class="dhead">
        <button class="btn" onclick={back}>← Wróć</button>
        <span class="dtitle">{openMeta?.title ?? ""}</span>
        <button class="btn" class:pinon={pinnedNoteId() === openId} onclick={() => openId && togglePin(openId)}>
          <Icon name="pin" size={13} />
          {pinnedNoteId() === openId ? "Przypięta" : "Przypnij"}
        </button>
      </div>
      {#if loading}
        <div class="empty">Wczytywanie…</div>
      {:else}
        <textarea
          bind:this={editor}
          class="editor"
          bind:value={text}
          oninput={() => openId && scheduleSaveNote(openId, text)}
          placeholder="Zacznij pisać… pierwsza linia staje się tytułem"
        ></textarea>
      {/if}
    </div>
  {/if}
</div>

<style>
  .notatki {
    flex: 1;
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 18px;
  }
  .bar,
  .list,
  .detail {
    width: min(860px, 100%);
    margin: 0 auto;
  }
  .bar {
    position: relative;
    display: flex;
    gap: 10px;
    margin-bottom: 12px;
  }
  .sicon {
    position: absolute;
    left: 11px;
    top: 50%;
    transform: translateY(-50%);
    display: flex;
    color: var(--text-dim-3);
    pointer-events: none;
  }
  .search {
    flex: 1;
    padding: 8px 12px 8px 32px;
    font: inherit;
    font-size: var(--fs-md);
    color: var(--text);
    background: var(--bg-deep);
    border: 1px solid var(--line-2);
    border-radius: var(--radius-md);
    outline: none;
  }
  .search:focus {
    border-color: var(--accent);
  }
  .list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 50px 0;
    font-size: var(--fs-md);
    color: var(--text-dim-3);
  }
  .row {
    position: relative;
    padding: 10px 76px 10px 14px;
    background: var(--bg-panel);
    border: 1px solid var(--line-2);
    border-radius: 10px;
    cursor: pointer;
    transition:
      border-color var(--t-fast),
      background var(--t-fast);
  }
  .row.active {
    border-color: var(--accent-a40);
    background: var(--bg-panel-2);
  }
  .row.pinned {
    border-left: 3px solid var(--accent);
  }
  .head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
  }
  .title {
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text-strong);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .date {
    flex-shrink: 0;
    font-size: 0.62rem;
    color: var(--text-dim-3);
  }
  .preview {
    margin-top: 4px;
    font-size: 0.7rem;
    line-height: 1.4;
    color: var(--text-dim-2);
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    white-space: pre-line;
  }
  .acts {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    gap: 2px;
  }
  .ib {
    display: flex;
    padding: 4px;
    color: var(--text-dim-3);
    background: none;
    border: 0;
    border-radius: 5px;
    cursor: pointer;
  }
  .ib:hover {
    color: var(--text);
    background: var(--hover);
  }
  .ib.on {
    color: var(--accent);
    background: var(--accent-a15);
  }
  .ib.del:hover {
    color: var(--danger);
  }
  .detail {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .dhead {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .dtitle {
    flex: 1;
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text-dim-1);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .pinon {
    color: var(--accent);
    border-color: var(--accent-a40);
    background: var(--accent-a10);
  }
  .editor {
    flex: 1;
    min-height: 0;
    resize: none;
    padding: 14px;
    font: inherit;
    font-size: 0.8rem;
    line-height: 1.6;
    color: var(--text);
    background: var(--bg-deep);
    border: 1px solid var(--line-1);
    border-radius: 10px;
    outline: none;
  }
  .editor:focus {
    border-color: var(--accent-a30);
  }
</style>
