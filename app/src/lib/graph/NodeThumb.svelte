<script lang="ts">
  // Middle slice of a node's volume output. The sidecar picks a pyramid level with an edge
  // just ≥ the thumbnail size (`fit`), so a thumbnail costs a few KB whatever the volume.
  import { getBinary } from "#lib/core/api.svelte.ts";
  import { activeWorkspaceId } from "#lib/core/workspace.svelte.ts";
  import { windowToRgba, type Slice, type Voxels } from "#lib/viewport/slices.ts";
  import { THUMB_H } from "./layout.ts";

  let {
    volRef,
    window,
    colors,
  }: { volRef: string; window?: { center: number; width: number }; colors?: Record<number, string> } = $props();

  let canvas = $state<HTMLCanvasElement>();
  const VIEWS: Record<string, new (b: ArrayBuffer) => Voxels> = {
    int16: Int16Array, uint16: Uint16Array, int32: Int32Array, uint8: Uint8Array, float32: Float32Array,
  };

  $effect(() => {
    const ref = volRef;
    const ctl = new AbortController();
    getBinary<{ shape: [number, number]; dtype: string }>(
      `/workspaces/${activeWorkspaceId()}/volumes/${ref}/slice?axis=k&index=-1&fit=${THUMB_H * 2}`,
      ctl.signal,
    )
      .then(({ meta, buffer }) => {
        if (!canvas) return;
        const data = new VIEWS[meta.dtype](buffer);
        const s: Slice = { rows: meta.shape[0], cols: meta.shape[1], data };
        let min = Infinity;
        let max = -Infinity;
        for (let i = 0; i < data.length; i++) {
          const v = data[i];
          if (v < min) min = v;
          if (v > max) max = v;
        }
        canvas.width = s.cols;
        canvas.height = s.rows;
        const img = new ImageData(s.cols, s.rows);
        const out = new Uint32Array(img.data.buffer);
        if (colors) {
          // label map: each label in its colour on black
          const lut = new Uint32Array(256).fill(0xff000000);
          for (const [k, hex] of Object.entries(colors)) {
            const v = parseInt(hex.slice(1), 16);
            lut[Number(k)] = 0xff000000 | ((v & 255) << 16) | (((v >> 8) & 255) << 8) | ((v >> 16) & 255);
          }
          for (let i = 0; i < data.length; i++) out[i] = lut[data[i] & 255];
        } else {
          const w = window ?? { center: (min + max) / 2, width: Math.max(1, max - min) };
          windowToRgba(s, w.center, w.width, out, { min, max });
        }
        canvas.getContext("2d")!.putImageData(img, 0, 0);
      })
      .catch(() => {});
    return () => ctl.abort();
  });
</script>

<div class="thumb" style:height="{THUMB_H}px"><canvas bind:this={canvas}></canvas></div>

<style>
  .thumb {
    margin: 4px 10px 8px;
    background: #000;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  canvas {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }
</style>
