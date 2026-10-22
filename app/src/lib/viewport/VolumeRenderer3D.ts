// 3-D volume rendering (GPU ray casting) through vtk.js, behind a small interface so the
// rest of the app never touches vtk.js objects (see docs/02-plan.md §2).

import "@kitware/vtk.js/Rendering/Profiles/Volume";
import vtkDataArray from "@kitware/vtk.js/Common/Core/DataArray";
import vtkImageData from "@kitware/vtk.js/Common/DataModel/ImageData";
import vtkPiecewiseFunction from "@kitware/vtk.js/Common/DataModel/PiecewiseFunction";
import vtkPlane from "@kitware/vtk.js/Common/DataModel/Plane";
import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";
import vtkColorTransferFunction from "@kitware/vtk.js/Rendering/Core/ColorTransferFunction";
import vtkVolume from "@kitware/vtk.js/Rendering/Core/Volume";
import vtkVolumeMapper from "@kitware/vtk.js/Rendering/Core/VolumeMapper";
import Constants from "@kitware/vtk.js/Rendering/Core/VolumeMapper/Constants";

import type { LevelGeometry } from "#lib/core/library.svelte.ts";
import { worldToIjk, type Vec3 } from "./geometry.ts";
import type { TransferFunction } from "./presets.ts";
import type { Voxels } from "./slices.ts";

const { BlendMode } = Constants;

/** vtk.js adapts the interactive resolution to hit this frame rate during gestures. */
const INTERACTIVE_FPS = 60;

function hex(h: string): [number, number, number] {
  const v = parseInt(h.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

/** Direction (world, no translation) → index-space direction. */
function linearIjk(g: LevelGeometry, v: Vec3): Vec3 {
  const d = g.direction;
  return [
    (d[0] * v[0] + d[3] * v[1] + d[6] * v[2]) / g.spacing[0],
    (d[1] * v[0] + d[4] * v[1] + d[7] * v[2]) / g.spacing[1],
    (d[2] * v[0] + d[5] * v[1] + d[8] * v[2]) / g.spacing[2],
  ];
}

/** Piecewise-linear opacity of a transfer function (points sorted by value). */
function opacityLookup(pts: TransferFunction["opacity"]): (v: number) => number {
  return (v) => {
    if (!(v === v) || !pts.length) return 0; // NaN = outside
    if (v <= pts[0][0]) return pts[0][1];
    for (let n = 1; n < pts.length; n++) {
      if (v <= pts[n][0]) {
        const [x0, o0] = pts[n - 1];
        const [x1, o1] = pts[n];
        return x1 === x0 ? o1 : o0 + ((v - x0) / (x1 - x0)) * (o1 - o0);
      }
    }
    return pts[pts.length - 1][1];
  };
}

/** Either box's centre lies inside the other (a crop of a volume, the volume of a crop). */
function sameRegion(a: number[], b: number[]): boolean {
  const inside = (p: number[], c: number[]) =>
    [0, 1, 2].every((n) => {
      const m = (p[2 * n] + p[2 * n + 1]) / 2;
      return m >= c[2 * n] && m <= c[2 * n + 1];
    });
  return inside(a, b) || inside(b, a);
}

export interface RenderStats {
  lastFrameMs: number;
}

export class VolumeRenderer3D {
  private grw = vtkGenericRenderWindow.newInstance({ background: [0, 0, 0], listenWindowResize: false });
  private mapper = vtkVolumeMapper.newInstance();
  private actor = vtkVolume.newInstance();
  private ctf = vtkColorTransferFunction.newInstance();
  private otf = vtkPiecewiseFunction.newInstance();
  private hasData = false;
  // label overlay (segments): its own volume actor
  private ovMapper = vtkVolumeMapper.newInstance();
  private ovActor = vtkVolume.newInstance();
  private ovCtf = vtkColorTransferFunction.newInstance();
  private ovOtf = vtkPiecewiseFunction.newInstance();
  private ovAdded = false;
  // CPU copies for picking and live brush edits (the arrays handed to vtk.js, not copies)
  private bg: { data: Voxels; g: LevelGeometry } | null = null;
  private ov: { data: Uint8Array; g: LevelGeometry; scalars: ReturnType<typeof vtkDataArray.newInstance> } | null = null;
  private lastTf: TransferFunction | null = null;
  private ghost = 1;
  private container: HTMLElement;
  private cameraListeners = new Set<() => void>();
  private clipPlanes: ReturnType<typeof vtkPlane.newInstance>[] = [];
  private interacting = 0;
  private raf = 0;
  private ro: ResizeObserver;
  stats: RenderStats = { lastFrameMs: 0 };

  constructor(container: HTMLElement) {
    this.container = container;
    this.grw.setContainer(container);
    this.grw.resize();
    this.ro = new ResizeObserver(() => {
      // hidden (display:none) in the current layout → nothing to size or draw
      if (!container.clientWidth || !container.clientHeight) return;
      this.grw.resize();
      this.render();
    });
    this.ro.observe(container);

    const prop = this.actor.getProperty();
    prop.setRGBTransferFunction(0, this.ctf);
    prop.setScalarOpacity(0, this.otf);
    prop.setInterpolationTypeToLinear();
    // 2 bytes/voxel on the GPU even without EXT_texture_norm16 (half float fallback).
    // present in vtk.js (VolumeProperty.js) but missing from its .d.ts
    (prop as unknown as { setPreferSizeOverAccuracy(v: boolean): void }).setPreferSizeOverAccuracy(true);
    prop.setAmbient(0.25);
    prop.setDiffuse(0.75);
    prop.setSpecular(0.35);
    prop.setSpecularPower(16);

    // Coarser rays while anything moves, full quality when it stops. vtk.js lowers the
    // render resolution adaptively to hold INTERACTIVE_FPS — but ONLY while its interactor
    // "animates", which is why our own gestures go through begin/endInteraction().
    this.mapper.setAutoAdjustSampleDistances(true);
    this.mapper.setInteractionSampleDistanceFactor(2.5);
    this.mapper.setInitialInteractionScale(4); // first gesture frame already at ½ × ½ resolution
    this.mapper.setMaximumSamplesPerRay(2000);
    this.actor.setMapper(this.mapper);

    const rw = this.grw.getRenderWindow();
    const rwi = rw.getInteractor();
    rwi.setDesiredUpdateRate(INTERACTIVE_FPS);
    // the mouse orbit/zoom/pan of vtk.js animates by itself; a full-quality frame at the end
    rwi.onEndAnimation(() => this.requestRender());
    // any camera change (mouse orbit/zoom, gizmo, reset) → overlays (gizmo, crop box) follow
    this.grw.getRenderer().getActiveCamera().onModified(() => {
      for (const cb of this.cameraListeners) cb();
    });
  }

  onCamera(cb: () => void): () => void {
    this.cameraListeners.add(cb);
    return () => this.cameraListeners.delete(cb);
  }

  /** World (LPS mm) → CSS px inside the container (y down). */
  project(w: Vec3): [number, number] {
    const W = this.container.clientWidth;
    const H = this.container.clientHeight;
    const nd = this.grw.getRenderer().worldToNormalizedDisplay(w[0], w[1], w[2], W / Math.max(H, 1));
    return [nd[0] * W, (1 - nd[1]) * H];
  }

  /** Camera axes in world space: right, up, and towards-the-viewer (−direction of projection). */
  cameraBasis(): { right: Vec3; up: Vec3; back: Vec3 } {
    const cam = this.grw.getRenderer().getActiveCamera();
    const dop = cam.getDirectionOfProjection() as Vec3;
    const up = cam.getViewUp() as Vec3;
    const right: Vec3 = [dop[1] * up[2] - dop[2] * up[1], dop[2] * up[0] - dop[0] * up[2], dop[0] * up[1] - dop[1] * up[0]];
    return { right, up, back: [-dop[0], -dop[1], -dop[2]] };
  }

  /** Put the camera on the `from` side of the focal point (unit vector), with `up` upwards. */
  viewFrom(from: Vec3, up: Vec3): void {
    const cam = this.grw.getRenderer().getActiveCamera();
    const f = cam.getFocalPoint();
    const d = cam.getDistance();
    cam.setPosition(f[0] + from[0] * d, f[1] + from[1] * d, f[2] + from[2] * d);
    cam.setViewUp(up[0], up[1], up[2]);
    this.grw.getRenderer().resetCameraClippingRange();
    this.render();
  }

  /** Zoom by a factor (>1 closer, <1 further). */
  zoomBy(f: number): void {
    this.grw.getRenderer().getActiveCamera().zoom(f);
    this.grw.getRenderer().resetCameraClippingRange();
    this.render();
  }

  /** Turntable orbit around the focal point (degrees). Coalesced to one render per frame. */
  orbit(azimuth: number, elevation: number): void {
    const cam = this.grw.getRenderer().getActiveCamera();
    cam.azimuth(azimuth);
    cam.elevation(elevation);
    cam.orthogonalizeViewUp();
    this.grw.getRenderer().resetCameraClippingRange();
    this.requestRender();
  }

  /**
   * Our own gestures (crop handles, sliders, gizmo drag): enter the interactor's animation
   * state so vtk.js renders every frame at adaptive (reduced) resolution and sample rate;
   * the last end renders once at full quality. Nested begin/end pairs are counted.
   */
  beginInteraction(): void {
    if (this.interacting++ === 0) this.grw.getRenderWindow().getInteractor().requestAnimation(this);
  }

  endInteraction(): void {
    if (this.interacting === 0) return;
    if (--this.interacting === 0) {
      this.grw.getRenderWindow().getInteractor().cancelAnimation(this);
      this.requestRender();
    }
  }

  /** At most one render per animation frame for programmatic changes. */
  requestRender(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => {
      this.raf = 0;
      this.render();
    });
  }

  /**
   * Axis-aligned crop: each plane keeps the side its normal points to; null removes them.
   * The planes are created ONCE and then only moved: changing the set of clipping planes
   * rebuilds the ray-casting shader (that was a ~1 s stall per mouse move).
   */
  setClipPlanes(planes: { origin: Vec3; normal: Vec3 }[] | null): void {
    const want = planes ?? [];
    if (want.length !== this.clipPlanes.length) {
      this.mapper.removeAllClippingPlanes();
      this.clipPlanes = want.map((p) => vtkPlane.newInstance({ origin: p.origin, normal: p.normal }));
      for (const p of this.clipPlanes) this.mapper.addClippingPlane(p);
    } else {
      want.forEach((p, n) => {
        this.clipPlanes[n].setOrigin(p.origin);
        this.clipPlanes[n].setNormal(p.normal);
      });
      this.mapper.modified();
    }
    this.requestRender();
  }

  /** Orthographic (Blender numpad 5) ↔ perspective, keeping the apparent size. */
  setOrthographic(on: boolean): void {
    const cam = this.grw.getRenderer().getActiveCamera();
    if (cam.getParallelProjection() === on) return;
    if (on) cam.setParallelScale(cam.getDistance() * Math.tan(((cam.getViewAngle() / 2) * Math.PI) / 180));
    cam.setParallelProjection(on);
    this.grw.getRenderer().resetCameraClippingRange();
    this.requestRender();
  }

  /**
   * Replace the volume. `data` is used as-is (no copy); geometry in LPS mm. The camera is
   * reset only for the first volume or one somewhere else entirely — a recomputed result
   * (preview → full, a re-cropped region) keeps the user's view.
   */
  setVolume(data: Voxels, g: LevelGeometry): void {
    const before = this.hasData ? this.actor.getBounds() : null;
    const image = vtkImageData.newInstance();
    image.setDimensions(g.size[0], g.size[1], g.size[2]);
    image.setSpacing([...g.spacing]);
    image.setOrigin([...g.origin]);
    // vtk.js direction is column-major: columns = i, j, k axes — our row-major D transposed.
    const d = g.direction;
    image.setDirection([d[0], d[3], d[6], d[1], d[4], d[7], d[2], d[5], d[8]]);
    image.getPointData().setScalars(vtkDataArray.newInstance({ name: "v", numberOfComponents: 1, values: data }));
    this.mapper.setInputData(image);
    this.bg = { data, g };
    const sd = Math.min(g.spacing[0], g.spacing[1], g.spacing[2]);
    this.mapper.setSampleDistance(sd * 0.7);
    this.actor.getProperty().setScalarOpacityUnitDistance(0, sd);
    const ren = this.grw.getRenderer();
    if (!this.hasData) ren.addVolume(this.actor);
    this.hasData = true;
    if (!before || !sameRegion(before, this.actor.getBounds())) this.resetCamera();
    this.render();
  }

  setTransferFunction(tf: TransferFunction): void {
    this.lastTf = tf;
    this.ctf.removeAllPoints();
    for (const [x, r, gg, b] of tf.color) this.ctf.addRGBPoint(x, r, gg, b);
    this.otf.removeAllPoints();
    for (const [x, o] of tf.opacity) this.otf.addPoint(x, o * this.ghost);
    this.actor.getProperty().setShade(tf.shade);
    this.mapper.setBlendMode(tf.mip ? BlendMode.MAXIMUM_INTENSITY_BLEND : BlendMode.COMPOSITE_BLEND);
    this.render();
  }

  /**
   * Segment overlay. A binary mask is interpolated linearly (smooth surface at the 0.5
   * iso-level); a multi-label map uses nearest neighbour so label colours never blend.
   * While an overlay is shown the background fades to a ghost for context.
   */
  setOverlay(data: Voxels | null, g: LevelGeometry | null, colors: Record<number, string>): void {
    const ren = this.grw.getRenderer();
    if (!data || !g) {
      if (this.ovAdded) ren.removeVolume(this.ovActor);
      this.ovAdded = false;
      this.ov = null;
      this.setGhost(1);
      return;
    }
    const image = vtkImageData.newInstance();
    image.setDimensions(g.size[0], g.size[1], g.size[2]);
    image.setSpacing([...g.spacing]);
    image.setOrigin([...g.origin]);
    const d = g.direction;
    image.setDirection([d[0], d[3], d[6], d[1], d[4], d[7], d[2], d[5], d[8]]);
    const scalars = vtkDataArray.newInstance({ name: "l", numberOfComponents: 1, values: data });
    image.getPointData().setScalars(scalars);
    this.ovMapper.setInputData(image);
    this.ov = data instanceof Uint8Array ? { data, g, scalars } : null;
    this.ovMapper.setSampleDistance(Math.min(...g.spacing) * 0.7);
    this.ovMapper.setAutoAdjustSampleDistances(true);
    this.ovMapper.setInteractionSampleDistanceFactor(2.5);
    const ids = Object.keys(colors).map(Number).filter((n) => n > 0);
    const binary = ids.length <= 1;
    const prop = this.ovActor.getProperty();
    this.ovCtf.removeAllPoints();
    this.ovOtf.removeAllPoints();
    this.ovOtf.addPoint(0, 0);
    if (binary) {
      const [r, gg, b] = hex(colors[ids[0] ?? 1] ?? "#7bc47f");
      this.ovCtf.addRGBPoint(0, r, gg, b);
      this.ovCtf.addRGBPoint(1, r, gg, b);
      this.ovOtf.addPoint(0.45, 0);
      this.ovOtf.addPoint(0.55, 0.9);
      this.ovOtf.addPoint(1, 0.9);
      prop.setInterpolationTypeToLinear();
    } else {
      for (const n of ids) {
        const [r, gg, b] = hex(colors[n]);
        this.ovCtf.addRGBPoint(n, r, gg, b);
        this.ovOtf.addPoint(n - 0.5, n === ids[0] ? 0 : 0.9);
        this.ovOtf.addPoint(n, 0.9);
      }
      prop.setInterpolationTypeToNearest();
    }
    prop.setRGBTransferFunction(0, this.ovCtf);
    prop.setScalarOpacity(0, this.ovOtf);
    prop.setScalarOpacityUnitDistance(0, Math.min(...g.spacing));
    prop.setShade(true);
    prop.setAmbient(0.3);
    prop.setDiffuse(0.75);
    prop.setSpecular(0.25);
    this.ovActor.setMapper(this.ovMapper);
    if (!this.ovAdded) ren.addVolume(this.ovActor);
    this.ovAdded = true;
    this.setGhost(0.18);
  }

  private setGhost(f: number): void {
    if (this.ghost === f) return this.requestRender();
    this.ghost = f;
    if (this.lastTf) this.setTransferFunction(this.lastTf);
    else this.requestRender();
  }

  /**
   * What is under a CSS pixel: the first overlay voxel along the view ray, or (`tissue`)
   * the first background voxel the transfer function shows — whichever comes first.
   * CPU ray march at ½ voxel steps (~1–2 k samples, well under 1 ms). Null = empty space.
   */
  pick(x: number, y: number, what: { mask: boolean; tissue: boolean }): Vec3 | null {
    const box = this.bg?.g ?? this.ov?.g;
    if (!box) return null;
    const W = this.container.clientWidth;
    const H = this.container.clientHeight;
    const ren = this.grw.getRenderer();
    const nx = x / W;
    const ny = 1 - y / H;
    const a = ren.normalizedDisplayToWorld(nx, ny, 0.25, W / Math.max(H, 1)) as unknown as number[];
    const b = ren.normalizedDisplayToWorld(nx, ny, 0.75, W / Math.max(H, 1)) as unknown as number[];
    let dir: Vec3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const dop = this.grw.getRenderer().getActiveCamera().getDirectionOfProjection();
    if (dir[0] * dop[0] + dir[1] * dop[1] + dir[2] * dop[2] < 0) dir = [-dir[0], -dir[1], -dir[2]];
    const len = Math.hypot(...dir) || 1;
    dir = [dir[0] / len, dir[1] / len, dir[2] / len];
    const o: Vec3 = [a[0], a[1], a[2]];
    // entry / exit of the ray through the volume box (slab test in index space)
    const oi = worldToIjk(box, o);
    const di = linearIjk(box, dir);
    let t0 = -Infinity;
    let t1 = Infinity;
    for (let n = 0; n < 3; n++) {
      const lo = -0.5;
      const hi = box.size[n] - 0.5;
      if (Math.abs(di[n]) < 1e-12) {
        if (oi[n] < lo || oi[n] > hi) return null;
        continue;
      }
      let ta = (lo - oi[n]) / di[n];
      let tb = (hi - oi[n]) / di[n];
      if (ta > tb) [ta, tb] = [tb, ta];
      t0 = Math.max(t0, ta);
      t1 = Math.min(t1, tb);
    }
    if (t0 > t1) return null;
    const cam = this.grw.getRenderer().getActiveCamera();
    if (!cam.getParallelProjection()) {
      // never pick behind the eye when zoomed inside the volume
      const p = cam.getPosition();
      t0 = Math.max(t0, (p[0] - o[0]) * dir[0] + (p[1] - o[1]) * dir[1] + (p[2] - o[2]) * dir[2]);
    }
    const ov = what.mask ? this.ov : null;
    const bg = what.tissue && this.bg && this.lastTf ? this.bg : null;
    const opacity = bg ? opacityLookup(this.lastTf!.opacity) : null;
    const sample = (gg: LevelGeometry, d: ArrayLike<number>, t: number): number => {
      const q = worldToIjk(gg, [o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t]);
      const i = Math.round(q[0]);
      const j = Math.round(q[1]);
      const k = Math.round(q[2]);
      if (i < 0 || j < 0 || k < 0 || i >= gg.size[0] || j >= gg.size[1] || k >= gg.size[2]) return NaN;
      return d[(k * gg.size[1] + j) * gg.size[0] + i];
    };
    const step = 0.5 * Math.min(...(ov?.g ?? box).spacing, ...box.spacing);
    for (let t = t0; t <= t1; t += step) {
      if (ov && sample(ov.g, ov.data, t) > 0) return [o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t];
      if (bg && opacity!(sample(bg.g, bg.data, t)) > 0.08)
        return [o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t];
    }
    return null;
  }

  /**
   * Live brush on the overlay: a world sphere of r mm set to 1 (add) or 0 (erase), the same
   * voxel test as the sidecar's edit node. No overlay yet (empty start) → an empty one on
   * the background grid. The texture is re-uploaded once per frame by vtk.js.
   */
  paint(center: Vec3, r: number, add: boolean, color: string): void {
    if (!this.ov) {
      if (!add || !this.bg) return;
      const g = this.bg.g;
      this.setOverlay(new Uint8Array(g.size[0] * g.size[1] * g.size[2]), g, { 1: color });
      if (!this.ov) return;
    }
    const { data, g, scalars } = this.ov;
    const c = worldToIjk(g, center);
    const rv = [r / g.spacing[0], r / g.spacing[1], r / g.spacing[2]];
    const lo = [0, 1, 2].map((n) => Math.max(0, Math.floor(c[n] - rv[n])));
    const hi = [0, 1, 2].map((n) => Math.min(g.size[n] - 1, Math.ceil(c[n] + rv[n])));
    const v = add ? 1 : 0;
    let changed = false;
    for (let k = lo[2]; k <= hi[2]; k++) {
      const dk = (k - c[2]) / rv[2];
      for (let j = lo[1]; j <= hi[1]; j++) {
        const dj = (j - c[1]) / rv[1];
        const rest = 1 - dk * dk - dj * dj;
        if (rest < 0) continue;
        const row = (k * g.size[1] + j) * g.size[0];
        for (let i = lo[0]; i <= hi[0]; i++) {
          const di = (i - c[0]) / rv[0];
          if (di * di <= rest && data[row + i] !== v) {
            data[row + i] = v;
            changed = true;
          }
        }
      }
    }
    if (!changed) return;
    scalars.modified();
    this.requestRender();
  }

  /** Anterior view, head up (LPS: camera on −y looking towards +y, view-up +z). */
  resetCamera(): void {
    const ren = this.grw.getRenderer();
    const cam = ren.getActiveCamera();
    const b = this.actor.getBounds();
    const c = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2];
    cam.setFocalPoint(c[0], c[1], c[2]);
    cam.setPosition(c[0], c[1] - 1000, c[2]);
    cam.setViewUp(0, 0, 1);
    ren.resetCamera();
    cam.zoom(1.3);
    ren.resetCameraClippingRange();
  }

  render(): void {
    if (!this.hasData) return;
    const t = performance.now();
    this.grw.getRenderWindow().render();
    this.stats.lastFrameMs = performance.now() - t;
  }

  /** Average ms per frame over n renders with the camera orbiting (benchmark helper). */
  benchmarkOrbit(n = 60): number {
    const cam = this.grw.getRenderer().getActiveCamera();
    const gl = (this.grw.getApiSpecificRenderWindow() as unknown as { getContext(): WebGL2RenderingContext }).getContext();
    const px = new Uint8Array(4);
    const t = performance.now();
    for (let i = 0; i < n; i++) {
      cam.azimuth(6);
      this.grw.getRenderWindow().render();
      // readPixels stalls until the GPU has finished the frame (gl.finish() does not in WebKit)
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    }
    return (performance.now() - t) / n;
  }

  dispose(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    if (this.interacting) this.grw.getRenderWindow().getInteractor().cancelAnimation(this);
    this.ro.disconnect();
    this.grw.delete();
  }
}
