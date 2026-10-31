// WebGL2 renderer for one 2-D slice (+ optional label overlay + live threshold preview).
//
// * The slice's typed array is uploaded AS IS into an integer texture (R16I / R16UI /
//   R32I / R8UI, or R32F for floats): no CPU conversion, no copy.
// * Window/level, bilinear interpolation and the screen→texel mapping (zoom, pan, flips,
//   anisotropic pixels) all happen in the fragment shader, so W/L drags, zoom and pan cost
//   one draw call and zero CPU work per frame.
// * Overlay: a label slice (R8UI) with its OWN screen→texel matrix — a mask may have another
//   resolution / extent than the background — coloured through a 256-entry LUT; fill + a
//   1-screen-pixel outline computed in screen space (always crisp).
// * Live threshold: voxels in [lo, hi] tinted directly from the background values — used
//   while a threshold slider is dragged, before the real mask comes back (60 fps, full res).

import type { Slice } from "./slices.ts";

type Kind = "i" | "u" | "f";

interface Fmt {
  kind: Kind;
  internal: number;
  format: number;
  type: number;
}

function formatOf(gl: WebGL2RenderingContext, data: Slice["data"]): Fmt {
  if (data instanceof Int16Array) return { kind: "i", internal: gl.R16I, format: gl.RED_INTEGER, type: gl.SHORT };
  if (data instanceof Uint16Array)
    return { kind: "u", internal: gl.R16UI, format: gl.RED_INTEGER, type: gl.UNSIGNED_SHORT };
  if (data instanceof Int32Array) return { kind: "i", internal: gl.R32I, format: gl.RED_INTEGER, type: gl.INT };
  if (data instanceof Uint8Array)
    return { kind: "u", internal: gl.R8UI, format: gl.RED_INTEGER, type: gl.UNSIGNED_BYTE };
  return { kind: "f", internal: gl.R32F, format: gl.RED, type: gl.FLOAT };
}

const VS = `#version 300 es
void main() {
  // one triangle covering the viewport
  vec2 p = vec2(float((gl_VertexID & 1) << 2) - 1.0, float((gl_VertexID & 2) << 1) - 1.0);
  gl_Position = vec4(p, 0.0, 1.0);
}`;

const FS = (kind: Kind) => `#version 300 es
precision highp float;
precision highp int;
uniform highp ${kind === "i" ? "isampler2D" : kind === "u" ? "usampler2D" : "sampler2D"} uTex;
uniform mat3 uFragToTex;   // gl_FragCoord.xy → texel coords (texel centres at +0.5)
uniform vec2 uWL;          // (lower bound, 1/width)
uniform ivec2 uSize;
uniform bool uSmooth;
// overlay
uniform highp usampler2D uLab;
uniform highp sampler2D uLut;      // 256 × 1 RGBA8, entry 0 unused
uniform mat3 uFragToLab;
uniform ivec2 uLabSize;
uniform bool uHasLab;
uniform float uLabAlpha;
uniform bool uOutline;
uniform bool uBgOn;       // false: a blended pass of ONE overlay (no background)
// pending brush strokes on the overlay grid: 0 keep, 1 add (label 1), 2 erase
uniform highp usampler2D uEdit;
uniform bool uHasEdit;
// live threshold: (lo, hi, enabled)
uniform vec3 uThr;
uniform vec3 uThrColor;
out vec4 outColor;

float fetchAt(ivec2 p) { return float(texelFetch(uTex, clamp(p, ivec2(0), uSize - 1), 0).r); }

uint labelAt(vec2 frag) {
  vec2 t = (uFragToLab * vec3(frag, 1.0)).xy;
  if (t.x < 0.0 || t.y < 0.0 || t.x >= float(uLabSize.x) || t.y >= float(uLabSize.y)) return 0u;
  ivec2 p = ivec2(floor(t));
  uint l = texelFetch(uLab, p, 0).r;
  if (uHasEdit) {
    uint e = texelFetch(uEdit, p, 0).r;
    if (e == 1u) l = 1u;
    else if (e == 2u) l = 0u;
  }
  return l;
}

vec4 overlayColor(uint l) {
  vec3 c = texelFetch(uLut, ivec2(int(l), 0), 0).rgb;
  float a = uLabAlpha;
  if (uOutline) {
    // screen-space edge: a neighbour pixel with another label → strong colour
    bool edge = labelAt(gl_FragCoord.xy + vec2(1.0, 0.0)) != l || labelAt(gl_FragCoord.xy - vec2(1.0, 0.0)) != l
             || labelAt(gl_FragCoord.xy + vec2(0.0, 1.0)) != l || labelAt(gl_FragCoord.xy - vec2(0.0, 1.0)) != l;
    if (edge) a = 0.95;
  }
  return vec4(c, a);
}

void main() {
  if (!uBgOn) {
    uint l0 = labelAt(gl_FragCoord.xy);
    outColor = l0 > 0u ? overlayColor(l0) : vec4(0.0);
    return;
  }
  vec2 t = (uFragToTex * vec3(gl_FragCoord.xy, 1.0)).xy;
  if (t.x < 0.0 || t.y < 0.0 || t.x > float(uSize.x) || t.y > float(uSize.y)) {
    outColor = vec4(0.0, 0.0, 0.0, 1.0);
    return;
  }
  float v;
  if (uSmooth) {
    vec2 q = t - 0.5;
    ivec2 i0 = ivec2(floor(q));
    vec2 f = q - floor(q);
    v = mix(mix(fetchAt(i0), fetchAt(i0 + ivec2(1, 0)), f.x),
            mix(fetchAt(i0 + ivec2(0, 1)), fetchAt(i0 + ivec2(1, 1)), f.x), f.y);
  } else {
    v = fetchAt(ivec2(floor(t)));
  }
  float g = clamp((v - uWL.x) * uWL.y, 0.0, 1.0);
  vec3 col = vec3(g);
  if (uThr.z > 0.5 && v >= uThr.x && v <= uThr.y) col = mix(col, uThrColor, 0.5);
  if (uHasLab) {
    uint l = labelAt(gl_FragCoord.xy);
    if (l > 0u) {
      vec4 oc = overlayColor(l);
      col = mix(col, oc.rgb, oc.a);
    }
  }
  outColor = vec4(col, 1.0);
}`;

interface Prog {
  prog: WebGLProgram;
  u: Record<string, WebGLUniformLocation | null>;
}

const UNIFORMS = [
  "uTex", "uFragToTex", "uWL", "uSize", "uSmooth", "uLab", "uLut", "uFragToLab", "uLabSize",
  "uHasLab", "uLabAlpha", "uOutline", "uBgOn", "uThr", "uThrColor", "uEdit", "uHasEdit",
];

export interface OverlayParams {
  /** renderer slot of the label slice (0 = the editable one) */
  slot: number;
  /** Row-major 3×3: device pixel (y down) → overlay texel coords. */
  screenToTex: number[];
  alpha: number;
  outline: boolean;
}

export interface DrawParams {
  /** Row-major 3×3: device pixel (x right, y DOWN from top-left) → texel coords. */
  screenToTex: number[];
  center: number;
  width: number;
  smooth: boolean;
  /** drawn bottom → top, each over the previous (alpha-blended passes) */
  overlays?: OverlayParams[];
  threshold?: { lo: number; hi: number; color: [number, number, number] } | null;
}

/** Column-major mat3 for uniformMatrix3fv, with gl_FragCoord's y-up folded in. */
function fragMatrix(m: number[], H: number): number[] {
  const r = mul3(m, [1, 0, 0, 0, -1, H, 0, 0, 1]);
  return [r[0], r[3], r[6], r[1], r[4], r[7], r[2], r[5], r[8]];
}

/** One label overlay: its slice, pending-stroke mask and colour table. */
interface Slot {
  lab: WebGLTexture | null;
  labSize: [number, number];
  edit: WebGLTexture | null; // same size as `lab`
  hasEdit: boolean;
  lut: WebGLTexture;
}

export class SliceRenderer {
  private gl: WebGL2RenderingContext;
  private progs = new Map<Kind, Prog>();
  private tex: WebGLTexture | null = null;
  private slots: Slot[] = [];
  private noLab: WebGLTexture; // 1×1 R8UI bound when there is no overlay (sampler must match)
  private vao: WebGLVertexArrayObject | null;
  private kind: Kind = "i";
  private size: [number, number] = [0, 0];
  private lost = false;

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", {
      antialias: false,
      depth: false,
      stencil: false,
      alpha: false,
      preserveDrawingBuffer: false,
      powerPreference: "high-performance",
    });
    if (!gl) throw new Error("WebGL2 niedostępne");
    this.gl = gl;
    this.vao = gl.createVertexArray();
    this.noLab = this.texture(null, gl.R8UI, 1, 1);
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.lost = true;
    });
  }

  get hasSlice(): boolean {
    return this.tex !== null;
  }

  private program(kind: Kind): Prog {
    let p = this.progs.get(kind);
    if (p) return p;
    const gl = this.gl;
    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FS(kind)));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) ?? "link");
    p = { prog, u: Object.fromEntries(UNIFORMS.map((n) => [n, gl.getUniformLocation(prog, n)])) };
    this.progs.set(kind, p);
    return p;
  }

  private texture(prev: WebGLTexture | null, internal: number, w: number, h: number): WebGLTexture {
    const gl = this.gl;
    if (prev) gl.deleteTexture(prev);
    const t = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texStorage2D(gl.TEXTURE_2D, 1, internal, w, h);
    // integer textures are never filterable; interpolation happens in the shader
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  }

  upload(s: Slice): void {
    if (this.lost) return;
    const gl = this.gl;
    const f = formatOf(gl, s.data);
    if (!this.tex || f.kind !== this.kind || this.size[0] !== s.cols || this.size[1] !== s.rows) {
      this.tex = this.texture(this.tex, f.internal, s.cols, s.rows);
      this.kind = f.kind;
      this.size = [s.cols, s.rows];
    } else gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, s.cols, s.rows, f.format, f.type, s.data);
  }

  private slot(n: number): Slot {
    let sl = this.slots[n];
    if (sl) return sl;
    const gl = this.gl;
    const lut = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, lut);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA8, 256, 1);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    sl = { lab: null, labSize: [0, 0], edit: null, hasEdit: false, lut };
    this.slots[n] = sl;
    return sl;
  }

  /** Label slice (uint8) into a slot. null removes the overlay. */
  uploadLabels(s: Slice | null, n = 0): void {
    if (this.lost) return;
    const gl = this.gl;
    const sl = this.slot(n);
    if (!s) {
      if (sl.lab) gl.deleteTexture(sl.lab);
      sl.lab = null;
      sl.hasEdit = false;
      return;
    }
    const data = s.data instanceof Uint8Array ? s.data : Uint8Array.from(s.data as ArrayLike<number>);
    if (!sl.lab || sl.labSize[0] !== s.cols || sl.labSize[1] !== s.rows) {
      sl.lab = this.texture(sl.lab, gl.R8UI, s.cols, s.rows);
      sl.labSize = [s.cols, s.rows];
      if (sl.edit) gl.deleteTexture(sl.edit);
      sl.edit = null;
      sl.hasEdit = false;
    } else gl.bindTexture(gl.TEXTURE_2D, sl.lab);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, s.cols, s.rows, gl.RED_INTEGER, gl.UNSIGNED_BYTE, data);
  }

  /** Pending-stroke mask on the label grid (rows × cols of the last label slice); null clears. */
  uploadEdit(data: Uint8Array | null): void {
    if (this.lost) return;
    const gl = this.gl;
    const sl = this.slot(0);
    const [w, h] = sl.labSize;
    if (!data || !sl.lab || data.length !== w * h) {
      sl.hasEdit = false;
      return;
    }
    if (!sl.edit) sl.edit = this.texture(null, gl.R8UI, w, h);
    else gl.bindTexture(gl.TEXTURE_2D, sl.edit);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, w, h, gl.RED_INTEGER, gl.UNSIGNED_BYTE, data);
    sl.hasEdit = true;
  }

  /** colors[n] = "#rrggbb" for label n (n ≥ 1). */
  setLut(colors: Record<number, string>, n = 0): void {
    if (this.lost) return;
    const gl = this.gl;
    const px = new Uint8Array(256 * 4);
    for (const [k, hex] of Object.entries(colors)) {
      const l = Number(k);
      if (l < 1 || l > 255) continue;
      const v = parseInt(hex.slice(1), 16);
      px.set([(v >> 16) & 255, (v >> 8) & 255, v & 255, 255], l * 4);
    }
    gl.bindTexture(gl.TEXTURE_2D, this.slot(n).lut);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 256, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
  }

  draw(p: DrawParams): void {
    if (this.lost) return;
    const gl = this.gl;
    const W = this.canvas.width;
    const H = this.canvas.height;
    gl.viewport(0, 0, W, H);
    if (!this.tex) {
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      return;
    }
    const { prog, u } = this.program(this.kind);
    gl.useProgram(prog);
    gl.bindVertexArray(this.vao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.uniform1i(u.uTex, 0);
    gl.uniformMatrix3fv(u.uFragToTex, false, fragMatrix(p.screenToTex, H));
    gl.uniform2f(u.uWL, p.center - p.width / 2, 1 / Math.max(p.width, 1e-9));
    gl.uniform2i(u.uSize, this.size[0], this.size[1]);
    gl.uniform1i(u.uSmooth, p.smooth ? 1 : 0);

    // pass 0: the background (+ live threshold); overlays follow as blended passes
    gl.disable(gl.BLEND);
    gl.uniform1i(u.uBgOn, 1);
    gl.uniform1i(u.uHasLab, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.noLab);
    gl.uniform1i(u.uLab, 1);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.slot(0).lut);
    gl.uniform1i(u.uLut, 2);
    gl.activeTexture(gl.TEXTURE3);
    gl.bindTexture(gl.TEXTURE_2D, this.noLab);
    gl.uniform1i(u.uEdit, 3);
    gl.uniform1i(u.uHasEdit, 0);
    const th = p.threshold;
    gl.uniform3f(u.uThr, th?.lo ?? 0, th?.hi ?? 0, th ? 1 : 0);
    gl.uniform3f(u.uThrColor, ...(th?.color ?? [0, 0, 0]));
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    const passes = (p.overlays ?? []).filter((o) => this.slots[o.slot]?.lab);
    if (!passes.length) return;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform1i(u.uBgOn, 0);
    for (const o of passes) {
      const sl = this.slots[o.slot];
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, sl.lab);
      gl.activeTexture(gl.TEXTURE2);
      gl.bindTexture(gl.TEXTURE_2D, sl.lut);
      gl.activeTexture(gl.TEXTURE3);
      gl.bindTexture(gl.TEXTURE_2D, sl.hasEdit && sl.edit ? sl.edit : this.noLab);
      gl.uniform1i(u.uHasEdit, sl.hasEdit ? 1 : 0);
      gl.uniformMatrix3fv(u.uFragToLab, false, fragMatrix(o.screenToTex, H));
      gl.uniform2i(u.uLabSize, sl.labSize[0], sl.labSize[1]);
      gl.uniform1f(u.uLabAlpha, o.alpha);
      gl.uniform1i(u.uOutline, o.outline ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    gl.disable(gl.BLEND);
  }

  clear(): void {
    if (this.lost) return;
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  dispose(): void {
    const gl = this.gl;
    if (this.tex) gl.deleteTexture(this.tex);
    for (const sl of this.slots) {
      if (!sl) continue;
      if (sl.lab) gl.deleteTexture(sl.lab);
      if (sl.edit) gl.deleteTexture(sl.edit);
      gl.deleteTexture(sl.lut);
    }
    gl.deleteTexture(this.noLab);
    for (const p of this.progs.values()) gl.deleteProgram(p.prog);
    gl.deleteVertexArray(this.vao);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}

export function mul3(a: number[], b: number[]): number[] {
  const r = new Array<number>(9);
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++) r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
  return r;
}
