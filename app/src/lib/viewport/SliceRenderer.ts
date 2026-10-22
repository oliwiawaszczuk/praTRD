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

void main() {
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
      vec3 c = texelFetch(uLut, ivec2(int(l), 0), 0).rgb;
      float a = uLabAlpha;
      if (uOutline) {
        // screen-space edge: a neighbour pixel with another label → strong colour
        bool edge = labelAt(gl_FragCoord.xy + vec2(1.0, 0.0)) != l || labelAt(gl_FragCoord.xy - vec2(1.0, 0.0)) != l
                 || labelAt(gl_FragCoord.xy + vec2(0.0, 1.0)) != l || labelAt(gl_FragCoord.xy - vec2(0.0, 1.0)) != l;
        if (edge) a = 0.95;
      }
      col = mix(col, c, a);
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
  "uHasLab", "uLabAlpha", "uOutline", "uThr", "uThrColor", "uEdit", "uHasEdit",
];

export interface OverlayParams {
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
  overlay?: OverlayParams | null;
  threshold?: { lo: number; hi: number; color: [number, number, number] } | null;
}

/** Column-major mat3 for uniformMatrix3fv, with gl_FragCoord's y-up folded in. */
function fragMatrix(m: number[], H: number): number[] {
  const r = mul3(m, [1, 0, 0, 0, -1, H, 0, 0, 1]);
  return [r[0], r[3], r[6], r[1], r[4], r[7], r[2], r[5], r[8]];
}

export class SliceRenderer {
  private gl: WebGL2RenderingContext;
  private progs = new Map<Kind, Prog>();
  private tex: WebGLTexture | null = null;
  private lab: WebGLTexture | null = null;
  private edit: WebGLTexture | null = null; // same size as `lab`
  private hasEdit = false;
  private lut: WebGLTexture;
  private noLab: WebGLTexture; // 1×1 R8UI bound when there is no overlay (sampler must match)
  private vao: WebGLVertexArrayObject | null;
  private kind: Kind = "i";
  private size: [number, number] = [0, 0];
  private labSize: [number, number] = [0, 0];
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
    this.lut = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.lut);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA8, 256, 1);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
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

  /** Label slice (uint8). null removes the overlay. */
  uploadLabels(s: Slice | null): void {
    if (this.lost) return;
    const gl = this.gl;
    if (!s) {
      if (this.lab) gl.deleteTexture(this.lab);
      this.lab = null;
      this.hasEdit = false;
      return;
    }
    const data = s.data instanceof Uint8Array ? s.data : Uint8Array.from(s.data as ArrayLike<number>);
    if (!this.lab || this.labSize[0] !== s.cols || this.labSize[1] !== s.rows) {
      this.lab = this.texture(this.lab, gl.R8UI, s.cols, s.rows);
      this.labSize = [s.cols, s.rows];
      if (this.edit) gl.deleteTexture(this.edit);
      this.edit = null;
      this.hasEdit = false;
    } else gl.bindTexture(gl.TEXTURE_2D, this.lab);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, s.cols, s.rows, gl.RED_INTEGER, gl.UNSIGNED_BYTE, data);
  }

  /** Pending-stroke mask on the label grid (rows × cols of the last label slice); null clears. */
  uploadEdit(data: Uint8Array | null): void {
    if (this.lost) return;
    const gl = this.gl;
    const [w, h] = this.labSize;
    if (!data || !this.lab || data.length !== w * h) {
      this.hasEdit = false;
      return;
    }
    if (!this.edit) this.edit = this.texture(null, gl.R8UI, w, h);
    else gl.bindTexture(gl.TEXTURE_2D, this.edit);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, w, h, gl.RED_INTEGER, gl.UNSIGNED_BYTE, data);
    this.hasEdit = true;
  }

  /** colors[n] = "#rrggbb" for label n (n ≥ 1). */
  setLut(colors: Record<number, string>): void {
    if (this.lost) return;
    const gl = this.gl;
    const px = new Uint8Array(256 * 4);
    for (const [k, hex] of Object.entries(colors)) {
      const n = Number(k);
      if (n < 1 || n > 255) continue;
      const v = parseInt(hex.slice(1), 16);
      px.set([(v >> 16) & 255, (v >> 8) & 255, v & 255, 255], n * 4);
    }
    gl.bindTexture(gl.TEXTURE_2D, this.lut);
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

    const ov = p.overlay && this.lab ? p.overlay : null;
    gl.uniform1i(u.uHasLab, ov ? 1 : 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lab ?? this.noLab);
    gl.uniform1i(u.uLab, 1);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.lut);
    gl.uniform1i(u.uLut, 2);
    gl.activeTexture(gl.TEXTURE3);
    gl.bindTexture(gl.TEXTURE_2D, this.hasEdit && this.edit ? this.edit : this.noLab);
    gl.uniform1i(u.uEdit, 3);
    gl.uniform1i(u.uHasEdit, ov && this.hasEdit ? 1 : 0);
    if (ov) {
      gl.uniformMatrix3fv(u.uFragToLab, false, fragMatrix(ov.screenToTex, H));
      gl.uniform2i(u.uLabSize, this.labSize[0], this.labSize[1]);
      gl.uniform1f(u.uLabAlpha, ov.alpha);
      gl.uniform1i(u.uOutline, ov.outline ? 1 : 0);
    }
    const th = p.threshold;
    gl.uniform3f(u.uThr, th?.lo ?? 0, th?.hi ?? 0, th ? 1 : 0);
    gl.uniform3f(u.uThrColor, ...(th?.color ?? [0, 0, 0]));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
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
    if (this.lab) gl.deleteTexture(this.lab);
    if (this.edit) gl.deleteTexture(this.edit);
    gl.deleteTexture(this.lut);
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
