// The keyboard-shortcuts window (one for the whole app; "?" opens it anywhere).

export type ShortcutSection = "scena" | "graf" | "tablica" | "ogolne";

let open = $state<ShortcutSection | "all" | null>(null);

export const shortcutsOpen = () => open;
export function openShortcuts(section: ShortcutSection | "all" = "all"): void {
  open = section;
}
export function closeShortcuts(): void {
  open = null;
}
