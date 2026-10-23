<script lang="ts">
  // Where each shown mesh cuts the slice plane, as a contour in the mesh colour (Slicer's
  // "slice intersection"); the geometry is in meshcut.ts.
  import { fetchMesh, type MeshData } from "#lib/core/meshes.svelte.ts";
  import type { MeshSpec, ViewProj } from "./layers.ts";
  import { contour, viewAffine } from "./meshcut.ts";

  let { proj, meshes }: { proj: ViewProj; meshes: MeshSpec[] } = $props();

  let loaded = $state.raw<{ spec: MeshSpec; data: MeshData }[]>([]);
  $effect(() => {
    const list = meshes;
    let live = true;
    if (!list.length) {
      loaded = [];
      return;
    }
    Promise.all(list.map((spec) => fetchMesh(spec.ref).then((data) => ({ spec, data }))))
      .then((ms) => live && (loaded = ms))
      .catch(() => {});
    return () => {
      live = false;
    };
  });

  const paths = $derived.by(() => {
    if (!loaded.length || !proj.W) return [];
    const a = viewAffine(proj);
    return loaded.map(({ spec, data }) => ({ key: spec.ref, color: spec.color, d: contour(data, a) }));
  });
</script>

{#if paths.length}
  <svg class="mk meshcut" aria-hidden="true">
    {#each paths as p (p.key)}
      <path d={p.d} fill="none" stroke="#000" stroke-opacity="0.55" stroke-width="3.5" stroke-linecap="round" />
      <path d={p.d} fill="none" stroke={p.color} stroke-width="1.8" stroke-linecap="round" />
    {/each}
  </svg>
{/if}

<style>
  .meshcut {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    pointer-events: none;
  }
</style>
