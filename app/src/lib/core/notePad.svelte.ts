// The floating note pad (pinned note, shown over every tab) and the "send to note" bridge:
// Cmd/Ctrl+click on a value (measurement, table cell, cursor position) appends it to the
// pinned note — besides copying it to the clipboard, which always happens.

import { getSetting, setSetting } from "./appSettings.svelte.ts";
import { toast } from "#lib/ui/toast.svelte.ts";

export type PadState = "min" | "medium" | "focus";

let pinned = $state<string | null>(null);
let state = $state<PadState>("min");
let restored = false;
let appendTarget: ((text: string) => void) | null = null;

/** After app settings are loaded: the pinned note survives a restart. */
export function restoreNotePad(): void {
  if (restored) return;
  restored = true;
  pinned = getSetting<string | null>("notatki_pinned", null);
  state = getSetting<PadState>("notatki_padState", "min") === "min" ? "min" : "medium";
}

export const pinnedNoteId = (): string | null => pinned;
export const padState = (): PadState => state;

export function setPinnedNote(id: string | null): void {
  pinned = id;
  setSetting("notatki_pinned", id);
}

export function setPadState(s: PadState): void {
  state = s;
  setSetting("notatki_padState", s);
}

export function registerAppendTarget(fn: ((text: string) => void) | null): void {
  appendTarget = fn;
}

/**
 * Copy a value: always to the clipboard; with the modifier (Cmd/Ctrl) also into the
 * pinned note at its cursor. Returns true when it went to the note.
 */
export function copyValue(text: string, e?: MouseEvent | KeyboardEvent): boolean {
  void navigator.clipboard?.writeText(text).catch(() => {});
  const toNote = !!e && (e.metaKey || e.ctrlKey) && !!pinned && !!appendTarget;
  if (toNote) {
    if (state === "min") setPadState("medium");
    appendTarget!(text);
    toast(`Do notatki: ${text}`, { icon: "note", ms: 1800 });
  } else toast(`Skopiowano: ${text}`, { icon: "check", ms: 1500 });
  return toNote;
}
