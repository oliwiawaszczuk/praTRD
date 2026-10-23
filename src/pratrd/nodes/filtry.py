"""Domain "Filtry": SimpleITK filters on volumes — edge-preserving denoising, edges, vesselness,
sharpening, greyscale morphology, arithmetic, masking, distance maps, N4 bias correction.

Local filters run on k-slabs with a margin wide enough for the filter's support, so memory
stays at one slab (not 3–4 full float copies of a 512²×2000 series), progress is reported
and the job can be cancelled between slabs. The slab result equals a whole-volume run inside
the core (the margin absorbs the border); tests check it. Every size is physical (mm).

Anisotropic diffusion is the exception (its conductance is scaled by the whole image's mean
gradient): it runs on the whole volume, with ITK progress / abort.

Smoothing-like results keep the input dtype; feature maps (gradient, vesselness, distance)
are float32 with their own display window.
"""

import math
from collections.abc import Callable
from typing import Any

import numpy as np
import SimpleITK as sitk

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import VolumeValue, resample_onto, to_sitk
from ..jobs import Cancelled
from ..volumes.geometry import Geometry

VOL, SEG = "wolumen", "segment"

SLAB_VOXELS = 16 << 20  # core voxels per slab (≈ 64 slices of 512²)


# ── helpers ────────────────────────────────────────────────────────────────────


def _vol(inputs: dict, port: str = "in") -> VolumeValue:
    for v in inputs.get(port) or []:
        if isinstance(v, VolumeValue) and v.kind == VOL:
            return v
    raise GraphError("Brak wolumenu na wejściu")


def _seg(inputs: dict, port: str) -> VolumeValue:
    for v in inputs.get(port) or []:
        if isinstance(v, VolumeValue) and v.kind == SEG:
            return v
    raise GraphError("Podłącz segment")


def _cast_like(arr: np.ndarray, like: np.dtype) -> np.ndarray:
    if np.issubdtype(like, np.integer):
        info = np.iinfo(like)
        return np.clip(np.rint(arr), info.min, info.max).astype(like)
    return arr.astype(like, copy=False)


def _sub_geometry(g: Geometry, k0: int, nk: int) -> Geometry:
    shift = g.matrix[:, 2] * g.spacing[2] * k0
    return Geometry(
        size=(g.size[0], g.size[1], nk),
        spacing=g.spacing,
        origin=tuple(float(x) for x in np.asarray(g.origin) + shift),  # type: ignore[arg-type]
        direction=g.direction,
    )


def slabbed(
    ctx: EvalContext,
    arr: np.ndarray,
    g: Geometry,
    margin_k: int,
    fn: Callable[[sitk.Image], sitk.Image],
    out_dtype: np.dtype,
    label: str,
    span: tuple[float, float] = (0.0, 1.0),
    share: float = 1.0,
) -> np.ndarray:
    """Apply an ITK filter slab by slab along k (each slab padded by `margin_k` slices).
    `share` < 1: smaller slabs for filters with big per-voxel buffers (e.g. a Hessian)."""
    nk = arr.shape[0]
    core = max(8, int(SLAB_VOXELS * share) // max(1, arr.shape[1] * arr.shape[2]))
    out = np.empty(arr.shape, dtype=out_dtype)
    a0, a1 = span
    for a in range(0, nk, core):
        b = min(nk, a + core)
        lo, hi = max(0, a - margin_k), min(nk, b + margin_k)
        img = to_sitk(np.ascontiguousarray(arr[lo:hi]), _sub_geometry(g, lo, hi - lo))
        # a view, not a copy — and `im` must stay referenced while it is used: a view does
        # not keep its ITK image alive (a temporary would leave garbage in `out`)
        im = fn(img)
        res = sitk.GetArrayViewFromImage(im)
        np.copyto(out[a:b], _cast_like(res[a - lo : b - lo], np.dtype(out_dtype)), casting="unsafe")
        del res, im
        ctx.report(a0 + (a1 - a0) * b / nk, label)
    return out


def _margin(g: Geometry, mm: float, extra: int = 2) -> int:
    return int(math.ceil(mm / g.spacing[2])) + extra


def window_of(arr: np.ndarray) -> dict[str, float]:
    """Display window from the 1st–99th percentile of a subsample (feature maps)."""
    step = max(1, int(round((arr.size / 2_000_000) ** (1 / 3))))
    s = arr[::step, ::step, ::step].astype(np.float32)
    lo, hi = (float(x) for x in np.nanpercentile(s, [1, 99.5]))
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1.0
    return {"center": round((lo + hi) / 2, 4), "width": round(hi - lo, 4)}


def _info(v: VolumeValue, suffix: str, arr: np.ndarray | None = None) -> dict[str, Any]:
    """Name with the operation; a feature map (`arr` given) gets its own window and no
    modality (CT presets in HU would make no sense on it)."""
    info = dict(v.info)
    info["name"] = f"{v.info.get('name', 'Wolumen')} · {suffix}"
    if arr is not None:
        info["window"] = window_of(arr)
        info["modality"] = ""
    return info


def _radius_vox(g: Geometry, mm: float) -> list[int]:
    return [max(0, int(round(mm / s))) for s in g.spacing]


class _Progress(sitk.Command):
    """ITK progress → node progress; a cancelled job aborts the running filter."""

    def __init__(self, ctx: EvalContext, filt: sitk.ProcessObject, span: tuple[float, float]):
        super().__init__()
        self.ctx, self.filt, self.span = ctx, filt, span
        self.cancelled = False

    def Execute(self) -> None:  # noqa: N802 — ITK callback name
        a, b = self.span
        try:
            self.ctx.report(a + (b - a) * self.filt.GetProgress())
        except Cancelled:
            self.cancelled = True
            self.filt.Abort()


def run_filter(ctx: EvalContext, filt: Any, *images: sitk.Image, span=(0.0, 1.0)) -> sitk.Image:
    cmd = _Progress(ctx, filt, span)
    filt.AddCommand(sitk.sitkProgressEvent, cmd)
    try:
        return filt.Execute(*images)
    except RuntimeError:
        if cmd.cancelled:
            raise Cancelled from None
        raise
    finally:
        filt.RemoveAllCommands()


# ── Odszumianie ────────────────────────────────────────────────────────────────


def _odszum(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    src = v.array()
    # whole volume, not slabs: the conductance is scaled by the image's mean gradient, so
    # per-slab runs would differ slightly and leave seams between slabs
    it = int(p["iterations"])
    curvature = p["method"] == "curvature"
    f = (
        sitk.CurvatureAnisotropicDiffusionImageFilter()
        if curvature
        else sitk.GradientAnisotropicDiffusionImageFilter()
    )
    # stability limit of the explicit 3-D scheme: min spacing / 2^(N+1), with a safety margin
    f.SetTimeStep(0.95 * min(g.spacing) / 16.0)
    f.SetConductanceParameter(float(p["conductance"]))
    f.SetNumberOfIterations(it)
    img = sitk.Cast(to_sitk(src, g), sitk.sitkFloat32)
    res = run_filter(ctx, f, img, span=(0.02, 0.9))
    del img
    out = _cast_like(sitk.GetArrayViewFromImage(res), src.dtype)
    name = "dyfuzja krzywiznowa" if curvature else "dyfuzja gradientowa"
    return {"out": ctx.volume_result(out, g, _info(v, f"{name} ×{it}"))}


register(
    NodeType(
        id="filtry/odszumianie",
        label="Odszumianie",
        domain="filtry",
        stage="przetwarzanie",
        description="Usuwa szum, a zostawia ostre krawędzie (w przeciwieństwie do Gaussa): dyfuzja anizotropowa "
        "wygładza wewnątrz tkanek, nie przez ich granice. Iteracje = siła, przewodność = jak łatwo wygładza przez "
        "słabe krawędzie. **Krzywiznowa** — gładkie powierzchnie, bez schodków; **gradientowa** (Perona–Malik) — "
        "ostrzejsze granice, szybsza.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "method",
                "Dyfuzja",
                "select",
                "curvature",
                options=(("curvature", "Krzywizn."), ("gradient", "Gradient.")),
            ),
            Param("iterations", "Iteracje", "int", 5, min=1, max=30, step=1),
            Param(
                "conductance",
                "Przewodność",
                "number",
                1.5,
                min=0.3,
                max=5,
                step=0.1,
                help="Większa = mocniej wygładza także słabe krawędzie",
            ),
        ),  # fmt: skip
        run=_odszum,
        cost="heavy",
    )
)


# ── Krawędzie ──────────────────────────────────────────────────────────────────


def _krawedzie(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    s = float(p["sigma"])
    if p["method"] == "gradient":

        def fn(img: sitk.Image) -> sitk.Image:
            return sitk.GradientMagnitudeRecursiveGaussian(sitk.Cast(img, sitk.sitkFloat32), s)

        suffix = f"gradient σ {s:g} mm"
    else:

        def fn(img: sitk.Image) -> sitk.Image:
            # minus: bright blobs / ridges give a positive response
            return -sitk.LaplacianRecursiveGaussian(sitk.Cast(img, sitk.sitkFloat32), s, True)

        suffix = f"LoG σ {s:g} mm"
    out = slabbed(ctx, v.array(), g, _margin(g, 4 * s), fn, np.float32, "Krawędzie")
    return {"out": ctx.volume_result(out, g, _info(v, suffix, out))}


register(
    NodeType(
        id="filtry/krawedzie",
        label="Krawędzie",
        domain="filtry",
        stage="przetwarzanie",
        description="**Gradient** — jak szybko zmienia się wartość (jasne = krawędź), po wygładzeniu Gaussem o σ w mm. "
        "**LoG** (Laplasjan Gaussa, znormalizowany) — jasne plamki i grzbiety o rozmiarze ~σ. Wynik to mapa "
        "cech (float), np. do progowania albo podglądu granic.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "method",
                "Metoda",
                "select",
                "gradient",
                options=(("gradient", "Gradient"), ("log", "LoG")),
            ),
            Param("sigma", "σ", "number", 1.0, min=0.2, max=10, step=0.1, unit="mm"),
        ),
        run=_krawedzie,
        cost="heavy",
    )
)


# ── Naczyniowość (Frangi) ───────────────────────────────────────────────────────

_SHAPES = {"tube": 1, "plate": 2, "blob": 0}
_GAMMA = 0.25  # structureness threshold, for intensities normalised by the contrast param


def frangi_scales(lo: float, hi: float, n: int) -> list[float]:
    if n <= 1 or hi <= lo:
        return [lo]
    r = (hi / lo) ** (1 / (n - 1))  # geometric: equal relative steps between scales
    return [lo * r**k for k in range(n)]


def _naczynia(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    lo, hi = sorted((float(p["sigma_min"]), float(p["sigma_max"])))
    scales = frangi_scales(lo, hi, int(p["steps"]))
    contrast = max(float(p["contrast"]), 1e-6)
    dim = _SHAPES[p["shape"]]
    bright = bool(p["bright"])

    def fn(img: sitk.Image) -> sitk.Image:
        f = sitk.Cast(img, sitk.sitkFloat32)
        best = None
        for s in scales:
            # σ²-normalised (scale-invariant Hessian), intensities in units of the contrast
            sm = sitk.SmoothingRecursiveGaussian(f, s) * (s * s / contrast)
            o = sitk.ObjectnessMeasure(sm, 0.5, 0.5, _GAMMA, False, dim, bright)
            best = o if best is None else sitk.Maximum(best, o)
        return best

    # ITK builds a float64 Hessian (48 B/voxel) per scale: ½-size slabs, 3σ margin (≤ 1 %)
    out = slabbed(ctx, v.array(), g, _margin(g, 3 * hi), fn, np.float32, "Naczyniowość", share=0.5)
    info = _info(v, f"naczyniowość {lo:g}–{hi:g} mm", out)
    info["window"] = {"center": 0.4, "width": 0.8}  # 0..1 measure
    return {"out": ctx.volume_result(out, g, info)}


register(
    NodeType(
        id="filtry/naczyniowosc",
        label="Naczyniowość",
        domain="filtry",
        stage="przetwarzanie",
        description="Filtr Frangiego (wieloskalowy): 0…1 — jak bardzo okolica woksela wygląda jak **rurka** (naczynie), "
        "**płaszczyzna** (np. ściana, kora kości) albo **kula** (guzek). Promienie struktur od σ min do σ max (mm). "
        "Kontrast = o ile struktura jest jaśniejsza od tła (np. ~200 HU dla naczyń w CTA). Wynik zwykle "
        "progujesz (np. > 0,3) i łączysz z Wyspami.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "shape",
                "Kształt",
                "select",
                "tube",
                options=(("tube", "Rurki"), ("plate", "Płaszcz."), ("blob", "Kule")),
            ),
            Param("sigma_min", "σ min", "number", 0.5, min=0.2, max=10, step=0.1, unit="mm"),
            Param("sigma_max", "σ max", "number", 2.0, min=0.2, max=10, step=0.1, unit="mm"),
            Param("steps", "Skale", "int", 3, min=1, max=8, step=1),
            Param(
                "contrast",
                "Kontrast",
                "number",
                200,
                min=1,
                max=3000,
                step=1,
                help="Różnica jasności struktury i tła (jednostki obrazu, np. HU)",
            ),
            Param(
                "bright",
                "Jasne",
                "bool",
                True,
                help="Jasne struktury na ciemnym tle (wyłącz: ciemne)",
            ),
        ),  # fmt: skip
        run=_naczynia,
        cost="heavy",
    )
)


# ── Wyostrz ────────────────────────────────────────────────────────────────────


def _wyostrz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    s, amount = float(p["sigma"]), float(p["amount"])
    src = v.array()

    def fn(img: sitk.Image) -> sitk.Image:
        return sitk.UnsharpMask(sitk.Cast(img, sitk.sitkFloat32), [s] * 3, amount, 0.0, False)

    out = slabbed(ctx, src, g, _margin(g, 4 * s), fn, src.dtype, "Wyostrzanie")
    return {"out": ctx.volume_result(out, g, _info(v, f"wyostrz ×{amount:g}"))}


register(
    NodeType(
        id="filtry/wyostrz",
        label="Wyostrz",
        domain="filtry",
        stage="przetwarzanie",
        description="Maska nieostra: dodaje do obrazu jego szczegóły drobniejsze niż σ (mm), wzmocnione o siłę. "
        "Wyraźniejsze krawędzie drobnych struktur, ale też więcej szumu.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param("sigma", "σ", "number", 1.0, min=0.2, max=10, step=0.1, unit="mm"),
            Param("amount", "Siła", "number", 0.8, min=0.1, max=5, step=0.1),
        ),
        run=_wyostrz,
    )
)


# ── Morfologia w skali szarości ──────────────────────────────────────────────────

_GREY_OPS = {
    "dilate": ("dylatacja", sitk.GrayscaleDilate, 1),
    "erode": ("erozja", sitk.GrayscaleErode, 1),
    "open": ("otwarcie", sitk.GrayscaleMorphologicalOpening, 2),
    "close": ("zamknięcie", sitk.GrayscaleMorphologicalClosing, 2),
    "tophat": ("top-hat jasne", sitk.WhiteTopHat, 2),
    "blackhat": ("top-hat ciemne", sitk.BlackTopHat, 2),
}


def _morf_szarosci(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    rad = _radius_vox(g, float(p["radius"]))
    name, op, passes = _GREY_OPS[p["op"]]
    src = v.array()
    if not any(rad):
        return {"out": v}

    def fn(img: sitk.Image) -> sitk.Image:
        return op(img, rad, sitk.sitkBall)

    out = slabbed(ctx, src, g, rad[2] * passes + 1, fn, src.dtype, "Morfologia")
    return {"out": ctx.volume_result(out, g, _info(v, f"{name} {p['radius']:g} mm"))}


register(
    NodeType(
        id="filtry/morfologia_szarosci",
        label="Morfologia szarości",
        domain="filtry",
        stage="przetwarzanie",
        description="Morfologia na wartościach (nie na masce): dylatacja = maksimum w kuli o promieniu w mm, erozja = "
        "minimum, otwarcie usuwa jasne detale mniejsze od kuli, zamknięcie — ciemne. **Top-hat** zostawia same "
        "jasne (albo ciemne) detale mniejsze od kuli — np. naczynia i zwapnienia bez tła.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "op",
                "Operacja",
                "select",
                "tophat",
                options=tuple((k, n[0].capitalize()) for k, n in _GREY_OPS.items()),
            ),
            Param("radius", "Promień", "number", 2.0, min=0.2, max=15, step=0.1, unit="mm"),
        ),  # fmt: skip
        run=_morf_szarosci,
        cost="heavy",
    )
)


# ── Arytmetyka ─────────────────────────────────────────────────────────────────

_ARITH = {
    "add": ("A + B", lambda a, b: a + b),
    "sub": ("A − B", lambda a, b: a - b),
    "absdiff": ("|A − B|", lambda a, b: np.abs(a - b)),
    "mul": ("A × B", lambda a, b: a * b),
    "max": ("max", np.maximum),
    "min": ("min", np.minimum),
    "mean": ("średnia", lambda a, b: (a + b) * 0.5),
}


def _arytmetyka(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    a = _vol(inputs, "a")
    b = _vol(inputs, "b")
    g = a.geometry
    ctx.report(0.05, "Dopasowanie siatek")
    bb = resample_onto(b, g, linear=True)  # B on A's grid (identity when equal)
    aa = a.array()
    label, op = _ARITH[p["op"]]
    out = np.empty(aa.shape, np.float32)
    step = max(1, SLAB_VOXELS // max(1, aa.shape[1] * aa.shape[2]))
    for k in range(0, aa.shape[0], step):
        sl = slice(k, k + step)
        out[sl] = op(aa[sl].astype(np.float32), bb[sl].astype(np.float32))
        ctx.report(0.1 + 0.9 * min(1.0, (k + step) / aa.shape[0]), "Arytmetyka")
    info = _info(a, f"{label} {b.info.get('name', 'B')}", out)
    return {"out": ctx.volume_result(out, g, info)}


register(
    NodeType(
        id="filtry/arytmetyka",
        label="Arytmetyka",
        domain="filtry",
        stage="przetwarzanie",
        description="Działanie woksel po wokselu na dwóch wolumenach: suma, różnica (np. faza z kontrastem − bez "
        "kontrastu), |różnica|, iloczyn, maksimum, minimum, średnia. B jest próbkowany na siatkę A (liniowo, "
        "w świecie mm) — wolumeny nie muszą mieć tej samej siatki, ale powinny się pokrywać.",
        inputs=(Port("a", "A", VOL), Port("b", "B", VOL)),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "op",
                "Działanie",
                "select",
                "sub",
                options=tuple((k, v[0]) for k, v in _ARITH.items()),
            ),
        ),
        run=_arytmetyka,
    )
)


# ── Maskuj wolumen ─────────────────────────────────────────────────────────────


def _maskuj(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    s = _seg(inputs, "seg")
    g = v.geometry
    src = v.array()
    m = resample_onto(s, g, linear=False)
    fill = src.min() if p["fill"] == "min" else 0
    fill = np.asarray(fill).astype(src.dtype)
    keep_inside = p["mode"] == "inside"
    out = np.empty_like(src)
    step = max(1, SLAB_VOXELS // max(1, src.shape[1] * src.shape[2]))
    for k in range(0, src.shape[0], step):
        sl = slice(k, k + step)
        inside = m[sl] > 0
        np.copyto(out[sl], src[sl])
        out[sl][~inside if keep_inside else inside] = fill
        ctx.report(min(1.0, (k + step) / src.shape[0]), "Maskowanie")
    what = "w segmencie" if keep_inside else "bez segmentu"
    return {"out": ctx.volume_result(out, g, _info(v, f"{what} {s.info.get('name', '')}".strip()))}


register(
    NodeType(
        id="filtry/maskuj",
        label="Maskuj wolumen",
        domain="filtry",
        stage="przetwarzanie",
        description="Zostawia wartości tylko wewnątrz segmentu (albo tylko poza nim); reszta dostaje minimum obrazu "
        "(np. −1024 HU — znika w 3D) albo 0. Np. usunięcie stołu, kości lub innego narządu przed renderingiem 3D.",
        inputs=(Port("in", "Wolumen", VOL), Port("seg", "Segment", SEG)),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "mode",
                "Zostaw",
                "select",
                "inside",
                options=(("inside", "Wnętrze"), ("outside", "Resztę")),
            ),
            Param("fill", "Wypełnij", "select", "min", options=(("min", "Minimum"), ("zero", "0"))),
        ),
        run=_maskuj,
    )
)


# ── Mapa odległości ────────────────────────────────────────────────────────────


def _odleglosc(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _seg(inputs, "in")
    g = s.geometry
    img = to_sitk(s.array(), g)
    f = sitk.SignedMaurerDistanceMapImageFilter()
    f.SetInsideIsPositive(False)
    f.SetSquaredDistance(False)
    f.SetUseImageSpacing(True)
    f.SetBackgroundValue(0)
    d = run_filter(ctx, f, img, span=(0.05, 0.9))
    out = sitk.GetArrayFromImage(sitk.Cast(d, sitk.sitkFloat32))
    if p["mode"] == "outside":
        np.maximum(out, 0, out=out)
    elif p["mode"] == "inside":
        np.negative(out, out=out)
        np.maximum(out, 0, out=out)
    info = {
        "name": f"{s.info.get('name', 'Segment')} · odległość",
        "window": {"center": 0.0, "width": 40.0} if p["mode"] == "signed" else window_of(out),
        "modality": "",
        "sourceVid": s.info.get("sourceVid", ""),
    }
    return {"out": ctx.volume_result(out, g, info)}


register(
    NodeType(
        id="filtry/mapa_odleglosci",
        label="Mapa odległości",
        domain="filtry",
        stage="przetwarzanie",
        description="Odległość każdego woksela od brzegu segmentu w mm (dokładna, euklidesowa). Ze znakiem: wewnątrz "
        "ujemna, na zewnątrz dodatnia. Progowanie mapy daje margines o dokładnej grubości (np. 0–5 mm wokół guza) "
        "albo „głębokość” w segmencie.",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param(
                "mode",
                "Zakres",
                "select",
                "signed",
                options=(
                    ("signed", "Ze znakiem"),
                    ("outside", "Na zewnątrz"),
                    ("inside", "Wewnątrz"),
                ),
            ),
        ),  # fmt: skip
        run=_odleglosc,
        cost="heavy",
    )
)


# ── Korekcja pola N4 ───────────────────────────────────────────────────────────


def _n4(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _vol(inputs)
    g = v.geometry
    src = v.array()
    lo = float(src.min())
    shift = 1.0 - lo if lo < 1 else 0.0  # N4 models a multiplicative field: values must be > 0
    f = max(1, int(p["shrink"]))
    full = to_sitk(src, g)
    small = sitk.Cast(sitk.Shrink(full, [min(f, n) for n in full.GetSize()]), sitk.sitkFloat32)
    del full
    if shift:
        small = small + shift
    mask = sitk.OtsuThreshold(small, 0, 1, 200)
    n4 = sitk.N4BiasFieldCorrectionImageFilter()
    n4.SetMaximumNumberOfIterations([int(p["iterations"])] * 4)
    run_filter(ctx, n4, small, mask, span=(0.05, 0.8))
    # the fitted B-spline field evaluated slab by slab on the full grid (float64 per slab only)
    out = np.empty_like(src)
    step = max(1, SLAB_VOXELS // max(1, src.shape[1] * src.shape[2]))
    for k in range(0, src.shape[0], step):
        nk = min(step, src.shape[0] - k)
        ref = sitk.Image([g.size[0], g.size[1], nk], sitk.sitkUInt8)
        sg = _sub_geometry(g, k, nk)
        ref.SetSpacing(sg.spacing)
        ref.SetOrigin(sg.origin)
        ref.SetDirection(sg.direction)
        field = n4.GetLogBiasFieldAsImage(ref)  # referenced while its view is read
        lb = sitk.GetArrayViewFromImage(field)
        corr = (src[k : k + nk].astype(np.float32) + shift) * np.exp(-lb).astype(np.float32) - shift
        out[k : k + nk] = _cast_like(corr, src.dtype)
        del lb, field
        ctx.report(0.8 + 0.2 * (k + nk) / src.shape[0], "Pole N4")
    return {"out": ctx.volume_result(out, g, _info(v, "N4"))}


register(
    NodeType(
        id="filtry/n4",
        label="Korekcja pola N4",
        domain="filtry",
        stage="przetwarzanie",
        description="Usuwa łagodne zmiany jasności w poprzek obrazu (pole cewki w **MR**) — ta sama tkanka ma potem tę "
        "samą wartość w całym wolumenie, co poprawia progowanie. Pole szacowane na zmniejszonym obrazie "
        "(zmniejszenie ×N), w obszarze z progu Otsu. Dla CT zwykle niepotrzebne.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Wolumen", VOL),),
        params=(
            Param("shrink", "Zmniejsz ×", "int", 4, min=1, max=8, step=1),
            Param(
                "iterations",
                "Iteracje",
                "int",
                50,
                min=5,
                max=200,
                step=5,
                help="Na każdy z 4 poziomów",
            ),
        ),
        run=_n4,
        cost="heavy",
    )
)
