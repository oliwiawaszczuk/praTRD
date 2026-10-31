// 3-D volume rendering (GPU ray casting) and surfaces through vtk.js, behind a small
// interface so the rest of the app never touches vtk.js objects (see docs/02-plan.md §2).

import "@kitware/vtk.js/Rendering/Profiles/Volume";
import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";
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
import { ijkToWorld, worldToIjk, type Vec3 } from "./geometry.ts";
import { cutInGrid, type Cut } from "./cuts.ts";
import type { TransferFunction } from "./presets.ts";
import type { Voxels } from "./slices.ts";
import type { MeshData } from "#lib/core/meshes.svelte.ts";

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
  // further segment layers: display only (no paint / pick), one actor per ref
  private extras = new Map<string, { actor: ReturnType<typeof vtkVolume.newInstance>; mapper: ReturnType<typeof vtkVolumeMapper.newInstance> }>();
  // CPU copies for picking and live brush edits (the arrays handed to vtk.js, not copies)
  private bg: { data: Voxels; g: LevelGeometry } | null = null;
  private ov: { data: Uint8Array; g: LevelGeometry; scalars: ReturnType<typeof vtkDataArray.newInstance> } | null = null;
  // surfaces (mesh nodes): one actor per mesh ref, buffers handed to vtk.js as they came
  private meshes = new Map<string, { actor: ReturnType<typeof vtkActor.newInstance>; data: MeshData }>();
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
      // a new aspect moves every projected point (layout switch) — overlays must follow
      for (const cb of this.cameraListeners) cb();
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
      this.setGhost(this.extras.size || this.meshes.size ? 0.18 : 1);
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

  /**
   * Other visible segment layers next to the editable overlay. Unchanged refs keep their
   * actor; a colour change only rebuilds the (tiny) transfer functions.
   */
  setExtraOverlays(list: { ref: string; data: Voxels; g: LevelGeometry; colors: Record<number, string> }[]): void {
    const ren = this.grw.getRenderer();
    const want = new Set(list.map((e) => e.ref));
    for (const [ref, e] of this.extras) {
      if (want.has(ref)) continue;
      ren.removeVolume(e.actor);
      e.mapper.delete();
      e.actor.delete();
      this.extras.delete(ref);
    }
    for (const { ref, data, g, colors } of list) {
      let e = this.extras.get(ref);
      if (!e) {
        const image = vtkImageData.newInstance();
        image.setDimensions(g.size[0], g.size[1], g.size[2]);
        image.setSpacing([...g.spacing]);
        image.setOrigin([...g.origin]);
        const d = g.direction;
        image.setDirection([d[0], d[3], d[6], d[1], d[4], d[7], d[2], d[5], d[8]]);
        image.getPointData().setScalars(vtkDataArray.newInstance({ name: "l", numberOfComponents: 1, values: data }));
        const mapper = vtkVolumeMapper.newInstance();
        mapper.setInputData(image);
        mapper.setSampleDistance(Math.min(...g.spacing) * 0.7);
        mapper.setAutoAdjustSampleDistances(true);
        mapper.setInteractionSampleDistanceFactor(2.5);
        const actor = vtkVolume.newInstance();
        actor.setMapper(mapper);
        ren.addVolume(actor);
        e = { actor, mapper };
        this.extras.set(ref, e);
      }
      const prop = e.actor.getProperty();
      const ctf = vtkColorTransferFunction.newInstance();
      const otf = vtkPiecewiseFunction.newInstance();
      const ids = Object.keys(colors).map(Number).filter((n) => n > 0);
      otf.addPoint(0, 0);
      if (ids.length <= 1) {
        const [r, gg, b] = hex(colors[ids[0] ?? 1] ?? "#7bc47f");
        ctf.addRGBPoint(0, r, gg, b);
        ctf.addRGBPoint(1, r, gg, b);
        otf.addPoint(0.45, 0);
        otf.addPoint(0.55, 0.9);
        otf.addPoint(1, 0.9);
        prop.setInterpolationTypeToLinear();
      } else {
        for (const n of ids) {
          const [r, gg, b] = hex(colors[n]);
          ctf.addRGBPoint(n, r, gg, b);
          otf.addPoint(n - 0.5, n === ids[0] ? 0 : 0.9);
          otf.addPoint(n, 0.9);
        }
        prop.setInterpolationTypeToNearest();
      }
      prop.setRGBTransferFunction(0, ctf);
      prop.setScalarOpacity(0, otf);
      prop.setScalarOpacityUnitDistance(0, Math.min(...g.spacing));
      prop.setShade(true);
      prop.setAmbient(0.3);
      prop.setDiffuse(0.75);
      prop.setSpecular(0.25);
    }
    this.setGhost(this.ovAdded || this.extras.size || this.meshes.size ? 0.18 : 1);
    this.requestRender();
  }

  /**
   * Surfaces to show (replaces the previous set; unchanged refs keep their GPU buffers).
   * Opaque by default; with opacity < 1 the background ghost shows through.
   */
  setMeshes(list: { data: MeshData; color: string }[], opacity: number): void {
    const ren = this.grw.getRenderer();
    const want = new Set(list.map((m) => m.data.ref));
    for (const [ref, m] of this.meshes) {
      if (want.has(ref)) continue;
      ren.removeActor(m.actor);
      m.actor.getMapper()?.delete();
      m.actor.delete();
      this.meshes.delete(ref);
    }
    for (const { data, color } of list) {
      let m = this.meshes.get(data.ref);
      if (!m) {
        const pd = vtkPolyData.newInstance();
        pd.getPoints().setData(data.verts, 3);
        pd.getPolys().setData(data.cells);
        pd.getPointData().setNormals(vtkDataArray.newInstance({ name: "Normals", numberOfComponents: 3, values: data.normals }));
        const mapper = vtkMapper.newInstance({ scalarVisibility: false });
        mapper.setInputData(pd);
        const actor = vtkActor.newInstance();
        actor.setMapper(mapper);
        const prop = actor.getProperty();
        prop.setInterpolationToPhong();
        prop.setAmbient(0.15);
        prop.setDiffuse(0.8);
        prop.setSpecular(0.3);
        prop.setSpecularPower(20);
        ren.addActor(actor);
        m = { actor, data };
        this.meshes.set(data.ref, m);
      }
      const prop = m.actor.getProperty();
      prop.setColor(...hex(color));
      prop.setOpacity(opacity);
    }
    this.setGhost(this.ovAdded || this.extras.size || this.meshes.size ? 0.18 : 1);
    ren.resetCameraClippingRange();
    if (!this.hasData && this.meshes.size) {
      this.hasData = true; // a mesh without any volume still renders
      this.resetCamera();
    }
    this.requestRender();
  }

  /** Nearest ray–triangle hit (Möller–Trumbore) over all shown meshes, as ray parameter. */
  private hitMeshes(o: Vec3, dir: Vec3, tMin: number): number {
    let best = Infinity;
    for (const { data } of this.meshes.values()) {
      const b = data.bounds;
      // slab test on the mesh box first: most rays miss most meshes
      let t0 = tMin;
      let t1 = Infinity;
      for (let n = 0; n < 3; n++) {
        if (Math.abs(dir[n]) < 1e-12) {
          if (o[n] < b[2 * n] || o[n] > b[2 * n + 1]) t1 = -Infinity;
          continue;
        }
        let ta = (b[2 * n] - o[n]) / dir[n];
        let tb = (b[2 * n + 1] - o[n]) / dir[n];
        if (ta > tb) [ta, tb] = [tb, ta];
        t0 = Math.max(t0, ta);
        t1 = Math.min(t1, tb);
      }
      if (t0 > t1 || t0 > best) continue;
      const v = data.verts;
      const c = data.cells;
      for (let f = 0; f < data.nFaces; f++) {
        const ia = c[4 * f + 1] * 3;
        const ib = c[4 * f + 2] * 3;
        const ic = c[4 * f + 3] * 3;
        const e1x = v[ib] - v[ia], e1y = v[ib + 1] - v[ia + 1], e1z = v[ib + 2] - v[ia + 2];
        const e2x = v[ic] - v[ia], e2y = v[ic + 1] - v[ia + 1], e2z = v[ic + 2] - v[ia + 2];
        const px = dir[1] * e2z - dir[2] * e2y;
        const py = dir[2] * e2x - dir[0] * e2z;
        const pz = dir[0] * e2y - dir[1] * e2x;
        const det = e1x * px + e1y * py + e1z * pz;
        if (det > -1e-12 && det < 1e-12) continue;
        const inv = 1 / det;
        const sx = o[0] - v[ia], sy = o[1] - v[ia + 1], sz = o[2] - v[ia + 2];
        const u = (sx * px + sy * py + sz * pz) * inv;
        if (u < 0 || u > 1) continue;
        const qx = sy * e1z - sz * e1y;
        const qy = sz * e1x - sx * e1z;
        const qz = sx * e1y - sy * e1x;
        const w = (dir[0] * qx + dir[1] * qy + dir[2] * qz) * inv;
        if (w < 0 || u + w > 1) continue;
        const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
        if (t >= tMin && t < best) best = t;
      }
    }
    return best;
  }

  private setGhost(f: number): void {
    if (f === 1 && this.meshes.size) f = 0.18; // a mesh is still shown: keep the ghost
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
    const cam = this.grw.getRenderer().getActiveCamera();
    // nearest visible surface (mesh) along the ray — markups and the brush land on it
    let tEye = -Infinity;
    if (!cam.getParallelProjection()) {
      const p = cam.getPosition();
      tEye = (p[0] - o[0]) * dir[0] + (p[1] - o[1]) * dir[1] + (p[2] - o[2]) * dir[2];
    }
    const tMesh = what.tissue && this.meshes.size ? this.hitMeshes(o, dir, tEye) : Infinity;
    const at = (t: number): Vec3 => [o[0] + dir[0] * t, o[1] + dir[1] * t, o[2] + dir[2] * t];
    if (!box) return Number.isFinite(tMesh) ? at(tMesh) : null;
    // entry / exit of the ray through the volume box (slab test in index space)
    const oi = worldToIjk(box, o);
    const di = linearIjk(box, dir);
    let t0 = -Infinity;
    let t1 = Infinity;
    for (let n = 0; n < 3; n++) {
      const lo = -0.5;
      const hi = box.size[n] - 0.5;
      if (Math.abs(di[n]) < 1e-12) {
        if (oi[n] < lo || oi[n] > hi) t0 = Infinity;
        continue;
      }
      let ta = (lo - oi[n]) / di[n];
      let tb = (hi - oi[n]) / di[n];
      if (ta > tb) [ta, tb] = [tb, ta];
      t0 = Math.max(t0, ta);
      t1 = Math.min(t1, tb);
    }
    // never pick behind the eye when zoomed inside the volume; nothing behind a mesh either
    t0 = Math.max(t0, tEye);
    t1 = Math.min(t1, tMesh);
    if (t0 > t1) return Number.isFinite(tMesh) ? at(tMesh) : null;
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
      if (ov && sample(ov.g, ov.data, t) > 0) return at(t);
      // the ghosted background (while a mesh is shown) is not a surface to land on
      if (bg && !this.meshes.size && opacity!(sample(bg.g, bg.data, t)) > 0.08) return at(t);
    }
    return Number.isFinite(tMesh) ? at(tMesh) : null;
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

  /**
   * Scissors frame of the current camera for a shape drawn in CSS px: M maps world to
   * (x, y, ·, w) so that x/w, y/w are the shape's coordinates — tangent of the view angle for
   * perspective (the cut is a cone from the eye), mm for orthographic (a prism).
   */
  cutFrame(pts: [number, number][]): { M: number[]; poly: [number, number][] } {
    const cam = this.grw.getRenderer().getActiveCamera();
    const pos = cam.getPosition();
    const fp = cam.getFocalPoint();
    const vu = cam.getViewUp();
    const unit = (a: number[]): Vec3 => {
      const l = Math.hypot(a[0], a[1], a[2]) || 1;
      return [a[0] / l, a[1] / l, a[2] / l];
    };
    const cross = (a: Vec3, b: number[]): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const dop = unit([fp[0] - pos[0], fp[1] - pos[1], fp[2] - pos[2]]);
    const right = unit(cross(dop, vu));
    const up = cross(right, dop);
    const row = (e: Vec3) => [e[0], e[1], e[2], -(e[0] * pos[0] + e[1] * pos[1] + e[2] * pos[2])];
    const W = this.container.clientWidth;
    const H = Math.max(1, this.container.clientHeight);
    const aspect = W / H;
    const ortho = cam.getParallelProjection();
    const s = ortho ? cam.getParallelScale() : Math.tan(((cam.getViewAngle() / 2) * Math.PI) / 180);
    const M = ortho ? [...row(right), ...row(up), ...row(dop), 0, 0, 0, 1] : [...row(right), ...row(up), 0, 0, 0, 1, ...row(dop)];
    return { M, poly: pts.map(([x, y]) => [((2 * x) / W - 1) * s * aspect, (1 - (2 * y) / H) * s]) };
  }

  /** A scissors cut applied to the overlay in place (instant 3-D feedback, ~0.1–0.3 s). */
  applyCut(cut: Cut, color: string): void {
    if (!this.ov) {
      if (cut.mode !== "add" || !this.bg) return;
      const g = this.bg.g;
      this.setOverlay(new Uint8Array(g.size[0] * g.size[1] * g.size[2]), g, { 1: color });
      if (!this.ov) return;
    }
    const { data, g, scalars } = this.ov;
    const { A, b, inside } = cutInGrid(cut, g);
    const [ni, nj, nk] = g.size;
    const keep = cut.mode === "keep";
    const v = cut.mode === "add" ? 1 : 0;
    const a0 = A[0][0], a1 = A[1][0], a2 = A[2][0], a3 = A[3][0];
    for (let k = 0; k < nk; k++) {
      for (let j = 0; j < nj; j++) {
        let x = A[0][2] * k + A[0][1] * j + b[0];
        let y = A[1][2] * k + A[1][1] * j + b[1];
        let z = A[2][2] * k + A[2][1] * j + b[2];
        let w = A[3][2] * k + A[3][1] * j + b[3];
        const row = (k * nj + j) * ni;
        for (let i = 0; i < ni; i++) {
          const hit = inside(x, y, z, w);
          if (keep ? !hit : hit) data[row + i] = keep ? 0 : v;
          x += a0;
          y += a1;
          z += a2;
          w += a3;
        }
      }
    }
    scalars.modified();
    this.requestRender();
  }

  /** The current frame at full quality as an image (screenshots). */
  async capture(): Promise<HTMLImageElement> {
    const [shot] = this.grw.getRenderWindow().captureImages("image/png");
    const url = await shot;
    const img = new Image();
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = () => rej(new Error("capture"));
      img.src = url;
    });
    return img;
  }

  /**
   * World-space sphere around what the user is looking at: the segment (its non-zero voxels)
   * or, failing that, the shown meshes. null = nothing but the volume.
   */
  structureBounds(): { center: Vec3; radius: number } | null {
    const box = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity];
    const grow = (p: Vec3) => {
      for (let n = 0; n < 3; n++) {
        box[2 * n] = Math.min(box[2 * n], p[n]);
        box[2 * n + 1] = Math.max(box[2 * n + 1], p[n]);
      }
    };
    if (this.ov) {
      const { data, g } = this.ov;
      const [nx, ny, nz] = g.size;
      let lo = [nx, ny, nz];
      let hi = [-1, -1, -1];
      // one pass; rows are skipped as soon as the first/last hit of the row is known
      for (let k = 0; k < nz; k++)
        for (let j = 0; j < ny; j++) {
          const o = (k * ny + j) * nx;
          let a = 0;
          while (a < nx && !data[o + a]) a++;
          if (a === nx) continue;
          let b = nx - 1;
          while (!data[o + b]) b--;
          if (a < lo[0]) lo[0] = a;
          if (b > hi[0]) hi[0] = b;
          if (j < lo[1]) lo[1] = j;
          if (j > hi[1]) hi[1] = j;
          if (k < lo[2]) lo[2] = k;
          if (k > hi[2]) hi[2] = k;
        }
      if (hi[0] >= 0) {
        for (const i of [lo[0] - 0.5, hi[0] + 0.5])
          for (const j of [lo[1] - 0.5, hi[1] + 0.5])
            for (const k of [lo[2] - 0.5, hi[2] + 0.5]) grow(ijkToWorld(g, [i, j, k]));
      }
    }
    if (!isFinite(box[0])) for (const { data } of this.meshes.values()) {
      const b = data.bounds;
      grow([b[0], b[2], b[4]]);
      grow([b[1], b[3], b[5]]);
    }
    if (!isFinite(box[0])) return null;
    const center: Vec3 = [(box[0] + box[1]) / 2, (box[2] + box[3]) / 2, (box[4] + box[5]) / 2];
    return { center, radius: Math.hypot(box[1] - box[0], box[3] - box[2], box[5] - box[4]) / 2 };
  }

  /**
   * Centre the camera on a world point (same direction). With `fit` the camera is placed so
   * that the sphere fills the view (a small segment gets as big as a large one); without, it
   * frames the volume ~2× closer.
   */
  focusOn(p: Vec3, fit?: number): void {
    const ren = this.grw.getRenderer();
    const cam = ren.getActiveCamera();
    const b = this.bg ? this.actor.getBounds() : ren.computeVisiblePropBounds();
    const radius = fit ? Math.max(fit * 1.25, 2) : Math.hypot(b[1] - b[0], b[3] - b[2], b[5] - b[4]) / 2 || 100;
    const fp = cam.getFocalPoint();
    const pos = cam.getPosition();
    const d = [pos[0] - fp[0], pos[1] - fp[1], pos[2] - fp[2]];
    const len = Math.hypot(d[0], d[1], d[2]) || 1;
    const dist = radius / Math.sin(((cam.getViewAngle() / 2) * Math.PI) / 180) / (fit ? 1 : 2);
    cam.setFocalPoint(p[0], p[1], p[2]);
    cam.setPosition(p[0] + (d[0] / len) * dist, p[1] + (d[1] / len) * dist, p[2] + (d[2] / len) * dist);
    if (cam.getParallelProjection()) cam.setParallelScale(fit ? radius : radius / 2);
    ren.resetCameraClippingRange();
    this.requestRender();
  }

  /** Anterior view, head up (LPS: camera on −y looking towards +y, view-up +z). */
  resetCamera(): void {
    const ren = this.grw.getRenderer();
    const cam = ren.getActiveCamera();
    const b = this.bg ? this.actor.getBounds() : ren.computeVisiblePropBounds();
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
