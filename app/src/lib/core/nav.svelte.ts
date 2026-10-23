// Cross-tab navigation: any component can ask for a tab (e.g. "(i)" on a node card →
// Dokumentacja at that node; a viewport screenshot toast → Tablica). +page.svelte follows.

export type TabKey = "dane" | "scena" | "tablica" | "notatki" | "dokumentacja" | "ustawienia";

let request = $state<{ tab: TabKey; n: number } | null>(null);
let counter = 0;

export const navRequest = () => request;

export function goToTab(tab: TabKey): void {
  request = { tab, n: ++counter };
}
