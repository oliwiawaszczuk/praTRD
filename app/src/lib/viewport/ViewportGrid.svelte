<script lang="ts">
  // All four views stay mounted whatever the layout: hiding a view is a CSS change, so
  // switching layouts never re-creates WebGL contexts nor re-uploads the 3-D volume.
  import type { VolumeEntry, VolumeMeta } from "#lib/core/library.svelte.ts";
  import { scene, type ViewId } from "./scene.svelte.ts";
  import SliceView from "./SliceView.svelte";
  import View3D from "./View3D.svelte";
  import { NO_LAYERS, type SliceLayers } from "./layers.ts";

  let {
    vol,
    meta,
    frameKey,
    layers = NO_LAYERS,
  }: { vol: VolumeEntry; meta: VolumeMeta; frameKey: string; layers?: SliceLayers } = $props();

  // Slicer "four-up": axial | 3D / sagittal | coronal.
  const AREA: Record<ViewId, string> = { axial: "a", "3d": "d", sagittal: "s", coronal: "c" };

  const solo = $derived(scene.maximized ?? (scene.layout === "single" ? scene.single : null));
  const cls = $derived(solo ? "solo" : scene.layout);
  const visible = (v: ViewId) => !solo || solo === v;
</script>

<div class="grid {cls}">
  {#each ["axial", "3d", "sagittal", "coronal"] as const as v (v)}
    <div class="cell" style:grid-area={AREA[v]} class:hidden={!visible(v)}>
      <!-- a failing view shows its error in place instead of taking the tab down -->
      <svelte:boundary>
        {#if v === "3d"}
          <View3D {vol} {meta} {layers} />
        {:else}
          <SliceView plane={v} {vol} {meta} {frameKey} {layers} />
        {/if}
        {#snippet failed(error, reset)}
          <div class="failed">
            <span>{(error as Error)?.message ?? String(error)}</span>
            <button class="btn" onclick={reset}>Odśwież widok</button>
          </div>
        {/snippet}
      </svelte:boundary>
    </div>
  {/each}
</div>

<style>
  .grid {
    width: 100%;
    height: 100%;
    display: grid;
    gap: 2px;
    background: var(--bg-deepest);
  }
  .grid.quad {
    grid-template: "a d" 1fr "s c" 1fr / 1fr 1fr;
  }
  .grid.main3d {
    grid-template: "d a" 1fr "d s" 1fr "d c" 1fr / 2fr 1fr;
  }
  .grid.solo {
    grid-template: "a" 1fr / 1fr;
  }
  .grid.solo .cell {
    grid-area: a !important;
  }
  .cell {
    min-width: 0;
    min-height: 0;
    position: relative;
  }
  .hidden {
    display: none;
  }
  .failed {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
    align-items: center;
    justify-content: center;
    padding: 16px;
    font-size: var(--fs-xs);
    color: var(--danger);
    text-align: center;
    background: #000;
  }
</style>
