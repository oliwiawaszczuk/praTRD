<script lang="ts">
  // Floating note pad — mounted once in +page.svelte, over every tab, while a note is pinned.
  //  min    → a round pin button in the corner; click opens "medium"
  //  medium → small window, draggable by its header, read-only; hovering focuses it
  //  focus  → larger and editable; a click outside goes back to medium
  // Cmd/Ctrl+click on values in the app (core/notePad.svelte.ts: copyValue) is inserted at
  // the last caret position. Position = global UI chrome → app settings.
  import { onMount, tick } from "svelte";
  import { fly } from "svelte/transition";
  import Icon from "#lib/ui/Icon.svelte";
  import { getSetting, setSetting } from "#lib/core/appSettings.svelte.ts";
  import { padState, pinnedNoteId, registerAppendTarget, setPadState, setPinnedNote } from "#lib/core/notePad.svelte.ts";
  import { flushNote, getNote, loadNotes, notes, notesLoaded, scheduleSaveNote } from "./notes.svelte.ts";

  const MEDIUM: [number, number] = [260, 150];
  const FOCUS: [number, number] = [380, 440];
  const MARGIN = 16;

  // default: bottom-left (top-right holds tab buttons, bottom-right the job tray)
  let top = $state<number | null>(getSetting<number | null>("notatki_padTop", null));
  let left = $state(getSetting<number>("notatki_padLeft", MARGIN));
  let winH = $state(window.innerHeight);
  let dragging = false;
  let start = { x: 0, y: 0, top: 0, left: 0 };
  let root = $state<HTMLDivElement>();
  let area = $state<HTMLTextAreaElement>();
  let text = $state("");
  let loadedFor: string | null = null;
  let caret = 0;

  const title = $derived(notes().find((n) => n.id === pinnedNoteId())?.title ?? "");
  const size = $derived(padState() === "focus" ? FOCUS : MEDIUM);

  $effect(() => {
    const id = pinnedNoteId();
    if (!id) {
      loadedFor = null;
      text = "";
      return;
    }
    if (loadedFor === id) return;
    loadedFor = id;
    if (!notesLoaded()) void loadNotes();
    getNote(id)
      .then((t) => {
        text = t;
        caret = t.length;
      })
      .catch(() => setPinnedNote(null)); // the note was deleted elsewhere
  });

  function insert(s: string): void {
    const at = Math.min(caret, text.length);
    const sep = at > 0 && !/\s$/.test(text.slice(0, at)) ? " " : "";
    text = text.slice(0, at) + sep + s + text.slice(at);
    caret = at + sep.length + s.length;
    save();
    if (padState() === "medium") setPadState("focus");
    void tick().then(() => area?.setSelectionRange(caret, caret));
  }
  onMount(() => {
    registerAppendTarget(insert);
    return () => registerAppendTarget(null);
  });

  function save(): void {
    const id = pinnedNoteId();
    if (id) scheduleSaveNote(id, text);
  }
  const syncCaret = () => area && (caret = area.selectionStart ?? text.length);

  // the focused (bigger) pad slides up instead of leaving the window
  const y = $derived(Math.max(4, Math.min(top ?? winH - MEDIUM[1] - MARGIN, winH - size[1] - 8)));
  function onDown(e: PointerEvent): void {
    e.preventDefault();
    dragging = true;
    start = { x: e.clientX, y: e.clientY, top: y, left };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onMove(e: PointerEvent): void {
    if (!dragging) return;
    top = Math.min(Math.max(4, start.top + e.clientY - start.y), window.innerHeight - 40);
    left = Math.min(Math.max(4, start.left + e.clientX - start.x), window.innerWidth - 60);
  }
  function onUp(): void {
    if (!dragging) return;
    dragging = false;
    setSetting("notatki_padTop", top);
    setSetting("notatki_padLeft", left);
  }
  function onWindowDown(e: PointerEvent): void {
    if (padState() === "focus" && root && !root.contains(e.target as Node)) setPadState("medium");
  }
  function minimize(): void {
    void flushNote();
    setPadState("min");
  }
  function unpin(): void {
    void flushNote();
    setPinnedNote(null);
  }
</script>

<svelte:window onpointerdown={onWindowDown} onresize={() => (winH = window.innerHeight)} />

{#if pinnedNoteId()}
  {#if padState() === "min"}
    <div class="mini" transition:fly={{ y: -12, duration: 160 }}>
      <button class="pinbtn" title={title || "Przypięta notatka"} onclick={() => setPadState("medium")}>
        <Icon name="pin" size={16} />
      </button>
      <button class="unpin" title="Odepnij" onclick={unpin}>✕</button>
    </div>
  {:else}
    <div
      bind:this={root}
      class="pad"
      class:focus={padState() === "focus"}
      style:top="{y}px"
      style:left="{left}px"
      style:width="{size[0]}px"
      style:height="{size[1]}px"
      transition:fly={{ y: -12, duration: 160 }}
      onpointerenter={() => !dragging && padState() === "medium" && setPadState("focus")}
      role="dialog"
      aria-label="Przypięta notatka"
      tabindex="-1"
    >
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="head" onpointerdown={onDown} onpointermove={onMove} onpointerup={onUp}>
        <Icon name="pin" size={12} />
        <span class="t">{title || "Notatka"}</span>
        <button class="hb" title="Zwiń" onpointerdown={(e) => e.stopPropagation()} onclick={minimize}>—</button>
        <button class="hb" title="Odepnij" onpointerdown={(e) => e.stopPropagation()} onclick={unpin}>✕</button>
      </div>
      <textarea
        bind:this={area}
        bind:value={text}
        oninput={() => (save(), syncCaret())}
        onclick={syncCaret}
        onkeyup={syncCaret}
        onselect={syncCaret}
        readonly={padState() !== "focus"}
        placeholder="Cmd/Ctrl + klik na wartości w aplikacji dopisze ją tutaj…"
      ></textarea>
    </div>
  {/if}
{/if}

<style>
  .mini {
    position: fixed;
    bottom: 16px;
    left: 16px;
    z-index: 950;
  }
  .pinbtn {
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--accent);
    background: var(--bg-panel-2);
    border: 1px solid var(--accent-a40);
    border-radius: 50%;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4);
    cursor: pointer;
  }
  .unpin {
    position: absolute;
    top: -6px;
    right: -6px;
    width: 16px;
    height: 16px;
    font-size: 0.55rem;
    color: var(--text-dim-1);
    background: var(--bg-panel);
    border: 1px solid var(--line-3);
    border-radius: 50%;
    cursor: pointer;
    opacity: 0;
    transition: opacity var(--t-fast);
  }
  .mini:hover .unpin {
    opacity: 1;
  }
  .unpin:hover {
    color: var(--danger);
  }
  .pad {
    position: fixed;
    z-index: 950;
    display: flex;
    flex-direction: column;
    background: var(--bg-deep);
    border: 1px solid var(--accent-a30);
    border-radius: 10px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    overflow: hidden;
    transition:
      width 0.16s ease,
      height 0.16s ease;
  }
  .pad.focus {
    border-color: var(--accent-a70);
  }
  .head {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    color: var(--accent);
    background: var(--hover);
    border-bottom: 1px solid var(--line-1);
    cursor: grab;
    touch-action: none;
    -webkit-user-select: none;
    user-select: none;
  }
  .t {
    flex: 1;
    min-width: 0;
    font-size: 0.68rem;
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .hb {
    width: 18px;
    height: 18px;
    font-size: 0.7rem;
    color: var(--text-dim-2);
    background: none;
    border: 0;
    border-radius: 4px;
    cursor: pointer;
  }
  .hb:hover {
    color: var(--text-strong);
    background: var(--hover);
  }
  textarea {
    flex: 1;
    min-height: 0;
    resize: none;
    padding: 8px 10px;
    font: inherit;
    font-size: 0.72rem;
    line-height: 1.5;
    color: var(--text);
    background: transparent;
    border: 0;
    outline: none;
  }
</style>
