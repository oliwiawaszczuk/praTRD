<script lang="ts">
  import "@fontsource/jetbrains-mono/400.css";
  import "@fontsource/jetbrains-mono/600.css";
  import "#lib/ui/tokens.css";

  import { onMount, untrack, type Component } from "svelte";
  import { waitForSidecar } from "#lib/core/api.svelte.ts";
  import { flushWorkspace, loadWorkspaces, wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  import { flushAppSettings, loadAppSettings } from "#lib/core/appSettings.svelte.ts";
  import { onCloseRequested, onFileDrop, onWorkspaceMenu } from "#lib/core/tauri.ts";
  import { connectEvents } from "#lib/core/events.svelte.ts";
  import { loadLibrary } from "#lib/core/library.svelte.ts";
  import { scanPaths } from "#lib/tabs/dane/importFlow.svelte.ts";
  import Dane from "#lib/tabs/dane/Dane.svelte";
  import Scena from "#lib/tabs/scena/Scena.svelte";
  import { flushGraph } from "#lib/graph/store.svelte.ts";
  import JobTray from "#lib/ui/JobTray.svelte";
  import LoadingBar from "#lib/ui/LoadingBar.svelte";
  import {
    exportWorkspaceFlow,
    importWorkspaceFlow,
    newWorkspaceFlow,
  } from "#lib/core/workspaceActions.ts";
  import DialogHost from "#lib/ui/DialogHost.svelte";
  import Icon from "#lib/ui/Icon.svelte";
  import WorkspaceChip from "#lib/ui/WorkspaceChip.svelte";
  import Placeholder from "#lib/tabs/Placeholder.svelte";
  import Ustawienia from "#lib/tabs/ustawienia/Ustawienia.svelte";
  import Tablica from "#lib/tabs/tablica/Tablica.svelte";
  import Notatki from "#lib/tabs/notatki/Notatki.svelte";
  import Dokumentacja from "#lib/tabs/dokumentacja/Dokumentacja.svelte";
  import FloatingNotePad from "#lib/tabs/notatki/FloatingNotePad.svelte";
  import Toasts from "#lib/ui/Toasts.svelte";
  import ShortcutsModal from "#lib/ui/ShortcutsModal.svelte";
  import { navRequest, type TabKey } from "#lib/core/nav.svelte.ts";
  import { restoreNotePad } from "#lib/core/notePad.svelte.ts";
  import { flushNote } from "#lib/tabs/notatki/notes.svelte.ts";
  import { dropOnBoard, flushBoard } from "#lib/tabs/tablica/board.svelte.ts";
  import { flushAppDocs, loadAppDocs } from "#lib/tabs/dokumentacja/appdocs.svelte.ts";

  type Tab = TabKey;

  const TABS: { key: Tab; label: string }[] = [
    { key: "dane", label: "Dane" },
    { key: "scena", label: "Scena" },
    { key: "tablica", label: "Tablica" },
    { key: "notatki", label: "Notatki" },
    { key: "dokumentacja", label: "Dokumentacja" },
    { key: "ustawienia", label: "Ustawienia" },
  ];

  const PLACEHOLDERS: Partial<Record<Tab, { stage: string; text: string }>> = {};

  const COMPONENTS: Partial<Record<Tab, Component>> = {
    dane: Dane,
    scena: Scena,
    tablica: Tablica,
    notatki: Notatki,
    dokumentacja: Dokumentacja,
    ustawienia: Ustawienia,
  };

  type Boot = "booting" | "ready" | "error";
  let boot = $state<Boot>("booting");
  let bootMsg = $state("Uruchamianie silnika…");
  let bootProgress = $state(0);
  let errorMsg = $state("");

  let activeTab = $state<Tab>("dane");
  // Tabs mount on first visit and then stay mounted (hidden): heavy tabs (WebGL
  // viewports, graph canvas) must not rebuild GPU state on every switch.
  let visited = $state<Set<Tab>>(new Set());
  let chipOpen = $state(false);
  let dropping = $state(false);

  // cross-tab requests (node "(i)" → Dokumentacja, screenshot toast → Tablica)
  $effect(() => {
    const r = navRequest();
    if (r && boot === "ready") untrack(() => selectTab(r.tab));
  });

  function selectTab(t: Tab): void {
    activeTab = t;
    if (!visited.has(t)) visited = new Set(visited).add(t);
    wsSet("activeTab", t);
  }

  async function start(): Promise<void> {
    try {
      // Asymptotic fake progress while waiting: the real wait time is unknown.
      await waitForSidecar((ms) => (bootProgress = 70 * (1 - Math.exp(-ms / 2500))));
      bootMsg = "Wczytywanie workspace'u…";
      bootProgress = 80;
      await Promise.all([loadWorkspaces(), loadAppSettings(), loadAppDocs()]);
      restoreNotePad();
      connectEvents();
      await loadLibrary();
      bootProgress = 100;
      const saved = wsGet<Tab>("activeTab", "dane");
      selectTab(TABS.some((t) => t.key === saved) ? saved : "dane");
      boot = "ready";
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : String(e);
      boot = "error";
    }
  }

  onMount(() => {
    void start();
    const flushAll = () =>
      Promise.all([flushWorkspace(), flushAppSettings(), flushGraph(), flushNote(), flushBoard(), flushAppDocs()]).then(() => {});
    const unsubs = [
      onWorkspaceMenu((a) => {
        if (boot !== "ready") return;
        if (a === "new") newWorkspaceFlow();
        else if (a === "open") chipOpen = true;
        else if (a === "import") importWorkspaceFlow();
        else exportWorkspaceFlow();
      }),
      onCloseRequested(flushAll),
      onFileDrop({
        over: (on) => (dropping = on && boot === "ready"),
        drop: (paths) => {
          if (boot !== "ready") return;
          if (activeTab === "tablica" && dropOnBoard(paths)) return; // images onto the board
          selectTab("dane");
          void scanPaths(paths);
        },
      }),
    ];
    // Browser-only dev fallback (Tauri uses close-requested above).
    const onUnload = () => {
      void flushWorkspace({ keepalive: true });
      void flushAppSettings({ keepalive: true });
      void flushGraph({ keepalive: true });
      void flushNote({ keepalive: true });
      void flushBoard({ keepalive: true });
      void flushAppDocs({ keepalive: true });
    };
    window.addEventListener("pagehide", onUnload);
    return () => {
      window.removeEventListener("pagehide", onUnload);
      for (const u of unsubs) void u.then((f) => f());
    };
  });
</script>

{#if boot === "booting"}
  <div class="boot">
    <div class="boot-content">
      <span class="boot-logo"><Icon name="cube" size={56} /></span>
      <span class="boot-title">praTRD</span>
      <span class="boot-sub">{bootMsg}</span>
      <div class="track"><div class="bar" style:width="{bootProgress}%"></div></div>
    </div>
  </div>
{:else if boot === "error"}
  <div class="error">
    <span class="error-icon"><Icon name="alert" size={40} /></span>
    <span class="error-title">Nie udało się uruchomić</span>
    <span class="error-body">{errorMsg}</span>
    <span class="error-hint">
      Sidecar Pythona nie wystartował — szczegóły w <code>sidecar.log</code> w folderze danych. W trybie dev sprawdź <code>uv sync</code> w
      katalogu projektu i czy port nie jest zajęty.
    </span>
    <button class="btn primary" onclick={() => location.reload()}>Spróbuj ponownie</button>
  </div>
{:else}
  <div class="layout">
    <nav class="tabbar">
      {#each TABS as t (t.key)}
        <button class="tab" class:active={activeTab === t.key} onclick={() => selectTab(t.key)}>
          {t.label}
        </button>
      {/each}
      <span class="spacer"></span>
      <WorkspaceChip bind:open={chipOpen} />
    </nav>
    <LoadingBar />
    <main class="content">
      {#each TABS as t (t.key)}
        {#if visited.has(t.key)}
          {@const C = COMPONENTS[t.key]}
          {@const ph = PLACEHOLDERS[t.key]}
          <section class="pane" class:hidden={activeTab !== t.key}>
            <svelte:boundary>
              {#if C}
                <C />
              {:else if ph}
                <Placeholder title={t.label} stage={ph.stage} text={ph.text} />
              {/if}
              {#snippet failed(error, reset)}
                <div class="tab-failed">
                  <span class="error-title">Błąd w zakładce „{t.label}”</span>
                  <span class="error-body">{(error as Error)?.message ?? String(error)}</span>
                  <button class="btn primary" onclick={reset}>Załaduj ponownie</button>
                </div>
              {/snippet}
            </svelte:boundary>
          </section>
        {/if}
      {/each}
    </main>
  </div>
{/if}

{#if dropping}
  <div class="drop">
    <div class="drop-box">
      <Icon name="folderIn" size={36} />
      <span>{activeTab === "tablica" ? "Upuść obrazy na tablicę" : "Upuść, aby zaimportować serie"}</span>
    </div>
  </div>
{/if}

<FloatingNotePad />
<ShortcutsModal />
<Toasts />
<JobTray />
<DialogHost />

<style>
  /* ── Boot ───────────────────────────────────────────── */
  .boot {
    position: fixed;
    inset: 0;
    background: var(--bg-boot);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .boot-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    animation: rise 0.5s ease;
  }
  .boot-logo {
    display: flex;
    color: var(--accent);
    animation:
      bouncespin 1.1s cubic-bezier(0.4, 0, 0.2, 1) infinite,
      glow 2.2s ease-in-out infinite;
  }
  .boot-title {
    font-size: 2rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--text-strong);
  }
  .boot-sub {
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.4);
  }
  .track {
    width: 260px;
    height: 3px;
    margin-top: 8px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
    overflow: hidden;
  }
  .bar {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    box-shadow: 0 0 8px var(--accent-a70);
    transition: width 0.25s ease;
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(16px);
    }
  }
  @keyframes bouncespin {
    0% { transform: translateY(0) rotateY(0deg); }
    30% { transform: translateY(-22px) rotateY(200deg); }
    50% { transform: translateY(-26px) rotateY(250deg); }
    70% { transform: translateY(-10px) rotateY(320deg); }
    85% { transform: translateY(-2px) rotateY(350deg); }
    100% { transform: translateY(0) rotateY(360deg); }
  }
  @keyframes glow {
    0%, 100% { filter: drop-shadow(0 0 10px var(--accent-a40)); }
    50% { filter: drop-shadow(0 0 24px var(--accent-a90)); }
  }

  /* ── Error ──────────────────────────────────────────── */
  .error {
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 2rem;
    text-align: center;
  }
  .error-icon,
  .error-title {
    color: var(--danger);
  }
  .error-title {
    font-size: 1.4rem;
    font-weight: 600;
  }
  .error-body {
    font-size: 0.85rem;
    color: var(--text-dim-2);
    max-width: 480px;
    -webkit-user-select: text;
    user-select: text;
  }
  .error-hint {
    font-size: var(--fs-sm);
    color: var(--text-dim-4);
    max-width: 420px;
    line-height: 1.6;
  }

  /* ── Layout ─────────────────────────────────────────── */
  .layout {
    height: 100vh;
    display: flex;
    flex-direction: column;
    animation: fadein 0.35s ease;
  }
  @keyframes fadein {
    from {
      opacity: 0;
    }
  }
  .tabbar {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    padding: 10px 16px 0;
    flex-shrink: 0;
  }
  .spacer {
    flex: 1;
  }
  .tab {
    padding: 7px 18px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    background: var(--shade);
    border: 1px solid var(--line-1);
    border-bottom: none;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
    color: var(--text-dim-3);
    cursor: pointer;
    transition: background var(--t-fast), color var(--t-fast);
  }
  .tab:hover:not(.active) {
    background: var(--hover);
    color: var(--text-dim-1);
  }
  .tab.active {
    background: var(--bg-panel);
    color: var(--accent);
    border-color: var(--line-2);
    box-shadow: 0 -2px 8px var(--accent-a10);
  }
  .content {
    flex: 1;
    min-height: 0;
    display: flex;
    background: var(--bg-panel);
    border-top: 1px solid var(--line-2);
  }
  .pane {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
  }
  .hidden {
    display: none !important;
  }
  .tab-failed {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    text-align: center;
  }

  .drop {
    position: fixed;
    inset: 0;
    z-index: 950;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .drop-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 36px 56px;
    color: var(--accent);
    font-size: var(--fs-lg);
    border: 2px dashed var(--accent-a70);
    border-radius: 14px;
    background: var(--bg-panel);
  }
</style>
