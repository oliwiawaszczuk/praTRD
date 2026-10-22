<script lang="ts" module>
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  // one shared value: toggling in the crop editor also switches the scene's 3-D view
  let ortho = $state(wsGet<boolean>("scena_ortho", false));
</script>

<script lang="ts">
  // Perspective ↔ orthographic for any 3-D view (Blender: numpad 5). Shared by the scene's
  // 3-D view and the crop editor; remembered per workspace; "5" works while the pointer is
  // over the owning view (`hostHovered`).
  import type { VolumeRenderer3D } from "./VolumeRenderer3D.ts";

  let { renderer, hostHovered = false }: { renderer: VolumeRenderer3D | null; hostHovered?: boolean } = $props();

  $effect(() => {
    renderer?.setOrthographic(ortho);
  });
  function toggle(): void {
    ortho = !ortho;
    wsSet("scena_ortho", ortho);
  }
  function onKey(e: KeyboardEvent): void {
    const t = e.target as HTMLElement;
    if (!hostHovered || t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") return;
    if (e.key === "5" && !e.metaKey && !e.ctrlKey) toggle();
  }
</script>

<svelte:window onkeydown={onKey} />

<button
  class="proj"
  class:on={ortho}
  title={ortho ? "Ortograficzny — przełącz na perspektywę (5)" : "Perspektywa — przełącz na ortograficzny (5)"}
  ondblclick={(e) => e.stopPropagation()}
  onclick={toggle}
>
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
    {#if ortho}<path d="M4 6h16v12H4zM4 12h16M12 6v12" />{:else}<path d="M7 6h10l3 12H4zM5.5 12h13M12 6v12" />{/if}
  </svg>
</button>

<style>
  .proj {
    position: absolute;
    top: 112px;
    right: 40px;
    z-index: 5;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim-1);
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 50%;
    cursor: pointer;
  }
  .proj:hover {
    color: #fff;
    background: rgba(255, 255, 255, 0.14);
  }
  .proj.on {
    color: var(--accent);
    border-color: var(--accent-a40);
  }
</style>
