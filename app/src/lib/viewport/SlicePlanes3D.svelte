<script lang="ts" module>
  import { wsGet, wsSet } from "#lib/core/workspace.svelte.ts";
  let shown = $state(wsGet<boolean>("scena_planes3d", true));
</script>

<script lang="ts">
  // Where the 2-D views are, inside the 3-D view (Slicer's "slice planes in 3D"): one
  // outlined rectangle per view in its colour (axial red, coronal green, sagittal yellow)
  // plus the shared cursor point. An SVG overlay re-projected on camera / cursor change —
  // 12 points per frame, nothing touches the volume rendering.
  import { untrack } from "svelte";
  import type { LevelGeometry } from "#lib/core/library.svelte.ts";
  import { ijkToWorld, PLANE_COLOR, viewBasis, worldToIjk, type Plane, type Vec3 } from "./geometry.ts";
  import { scene } from "./scene.svelte.ts";
  import type { VolumeRenderer3D } from "./VolumeRenderer3D.ts";

  let { renderer, geometry }: { renderer: VolumeRenderer3D | null; geometry: LevelGeometry } = $props();

  let tick = $state(0);
  $effect(() => {
    const r = renderer;
    if (!r) return;
    let raf = 0;
    const off = r.onCamera(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => tick++);
    });
    untrack(() => tick++);
    return () => {
      off();
      cancelAnimationFrame(raf);
    };
  });

  const PLANES: Plane[] = ["sagittal", "coronal", "axial"];
  const pts = (a: [number, number][]) => a.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

  const shapes = $derived.by(() => {
    void tick;
    const c = scene.cursor;
    if (!renderer || !c || !shown) return null;
    const g = geometry;
    // clamped into the volume, exactly like the 2-D views clamp their slice
    const ijk = worldToIjk(g, c).map((x, n) => Math.min(g.size[n] - 0.5, Math.max(-0.5, x))) as Vec3;
    const planes = PLANES.map((plane) => {
      const s = viewBasis(g, plane).sliceAxis;
      const [a, b] = ([0, 1, 2] as const).filter((x) => x !== s);
      const at = ijk[s];
      const corner = (u: number, v: number) => {
        const p: Vec3 = [0, 0, 0];
        p[s] = at;
        p[a] = u ? g.size[a] - 0.5 : -0.5;
        p[b] = v ? g.size[b] - 0.5 : -0.5;
        return renderer!.project(ijkToWorld(g, p));
      };
      return { plane, color: PLANE_COLOR[plane], points: pts([corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)]) };
    });
    return { planes, cursor: renderer.project(ijkToWorld(g, ijk)) };
  });

  function toggle(): void {
    shown = !shown;
    wsSet("scena_planes3d", shown);
  }
</script>

{#if shapes}
  <svg class="planes" aria-hidden="true">
    {#each shapes.planes as p (p.plane)}
      <polygon points={p.points} fill={p.color} fill-opacity="0.07" stroke={p.color} stroke-opacity="0.9" stroke-width="1.5" />
    {/each}
    <circle cx={shapes.cursor[0]} cy={shapes.cursor[1]} r="4" fill="#fff" stroke="#000" stroke-width="1.5" />
  </svg>
{/if}

<button
  class="tgl"
  class:on={shown}
  title={shown ? "Ukryj położenie przekrojów 2D" : "Pokaż położenie przekrojów 2D"}
  ondblclick={(e) => e.stopPropagation()}
  onclick={toggle}
>
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke-width="1.8">
    <path d="M3 9l9-5 9 5-9 5z" stroke={PLANE_COLOR.axial} />
    <path d="M12 14v7" stroke={PLANE_COLOR.coronal} />
    <path d="M7 11.8v6.4M17 11.8v6.4" stroke={PLANE_COLOR.sagittal} />
  </svg>
</button>

<style>
  .planes {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .tgl {
    position: absolute;
    top: 148px;
    right: 40px;
    z-index: 5;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 50%;
    cursor: pointer;
    opacity: 0.55;
  }
  .tgl:hover {
    background: rgba(255, 255, 255, 0.14);
    opacity: 1;
  }
  .tgl.on {
    opacity: 1;
    border-color: var(--accent-a40);
  }
</style>
