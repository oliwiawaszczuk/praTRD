"""Domain "Segmentacja": binary segments (uint8 0/1) and label maps (uint8 0..N).

Every segment carries `info.ref` — the intensity volume it was derived from — so the
viewports can show it as an overlay on its own background. All sizes are physical (mm,
mm³) and all positions are world LPS mm, never voxel indices: the same graph gives the
same physical result on a preview level and at full resolution, and brush strokes / seeds
survive any change of the input geometry.
"""

from typing import Any

import numpy as np
import SimpleITK as sitk

from ..graph.evaluator import EvalContext, GraphError
from ..graph.types import NodeType, Param, Port, register
from ..graph.values import VolumeValue, from_sitk, resample_onto, to_sitk
from ..volumes.geometry import Geometry

VOL, SEG, LAB = "wolumen", "segment", "segmentacja"

PALETTE = [
    "#7bc47f",
    "#e05a5a",
    "#5b9bd5",
    "#e8c547",
    "#b48ce0",
    "#4db6ac",
    "#f2994a",
    "#f06292",
    "#c0ca33",
    "#90a4ae",
    "#8d6e63",
    "#26c6da",
]


# ── helpers ────────────────────────────────────────────────────────────────────


def _first(
    inputs: dict[str, list[Any]], port: str, kind: str, required: bool = True
) -> VolumeValue | None:
    for v in inputs.get(port) or []:
        if isinstance(v, VolumeValue) and v.kind == kind:
            return v
    if required:
        raise GraphError("Brak wejścia")
    return None


def _seg_info(name: str, ref: str, color: str = PALETTE[0], **extra: Any) -> dict[str, Any]:
    return {"name": name, "ref": ref, "color": color, **extra}


def _ref_of(v: VolumeValue) -> str:
    """Background (intensity) volume of a value: itself for volumes, its source for masks."""
    return v.ref if v.kind == VOL else v.info.get("ref", "")


def _on_grid(v: VolumeValue, g: Geometry) -> np.ndarray:
    """A label volume resampled (nearest neighbour) onto another grid — e.g. a preview mask
    combined with a full-resolution one, or masks from differently cropped inputs."""
    return resample_onto(v, g, linear=False)


def _world_to_index(g: Geometry, w: list[float]) -> tuple[int, int, int] | None:
    rel = np.asarray(w, dtype=np.float64) - np.asarray(g.origin)
    ijk = (g.matrix.T @ rel) / np.asarray(g.spacing)
    idx = np.rint(ijk).astype(int)
    if np.any(idx < 0) or np.any(idx >= np.asarray(g.size)):
        return None
    return int(idx[0]), int(idx[1]), int(idx[2])


def _radius_vox(g: Geometry, mm: float) -> list[int]:
    return [max(0, int(round(mm / s))) for s in g.spacing]


def _mask_out(ctx: EvalContext, mask: np.ndarray, g: Geometry, info: dict[str, Any]) -> VolumeValue:
    return ctx.volume_result(np.ascontiguousarray(mask, dtype=np.uint8), g, info, kind=SEG)


# ── Próg ───────────────────────────────────────────────────────────────────────


def _prog(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    lo, hi = sorted((p["lo"], p["hi"]))
    a = v.array()
    mask = (a >= lo) & (a <= hi)
    return {"out": _mask_out(ctx, mask, v.geometry, _seg_info(f"Próg {lo:g}–{hi:g}", _ref_of(v)))}


register(
    NodeType(
        id="segmentacja/prog",
        label="Próg",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Segment = woksele z wartością w zakresie [od, do]. W CT: kości ≈ 300+, naczynia z kontrastem ≈ 150–600 HU.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param("lo", "Od", "number", 300.0, min=-5000, max=50000, step=1),
            Param("hi", "Do", "number", 3071.0, min=-5000, max=50000, step=1),
        ),
        run=_prog,
        widget="threshold",
    )
)


# ── Otsu ───────────────────────────────────────────────────────────────────────


def _otsu(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    f = sitk.OtsuThresholdImageFilter()
    f.SetInsideValue(0)
    f.SetOutsideValue(1)  # bright class = foreground
    f.SetNumberOfHistogramBins(int(p["bins"]))
    out = f.Execute(to_sitk(v.array(), v.geometry))
    t = float(f.GetThreshold())
    mask, _ = from_sitk(out)
    return {
        "out": _mask_out(ctx, mask, v.geometry, _seg_info(f"Otsu > {t:.0f}", _ref_of(v))),
        "prog": round(t, 3),
    }


register(
    NodeType(
        id="segmentacja/otsu",
        label="Otsu",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Automatyczny próg (metoda Otsu) — dzieli histogram na tło i jasny obiekt. Drugie wyjście: wyliczona wartość progu.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG), Port("prog", "Próg", "liczba")),
        params=(Param("bins", "Koszyki", "int", 256, min=16, max=1024, step=16),),
        run=_otsu,
    )
)


# ── Region growing ──────────────────────────────────────────────────────────────


def _rozrost(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = _first(inputs, "in", VOL)
    seeds = [s for s in (_world_to_index(v.geometry, w) for w in p["seeds"]) if s is not None]
    if not seeds:
        raise GraphError("Kliknij ziarno w widoku 2D (narzędzie ziarna)")
    a = v.array()
    # Seed value + the bright side of a 2 mm neighbourhood: a click on the EDGE of a vessel
    # (partial volume, e.g. 449 HU) still reaches its interior (≈ 550 HU) through the 90th
    # percentile, while the surrounding soft tissue stays below seed − tolerance.
    rv = _radius_vox(v.geometry, 2.0)
    vals = []  # value at each seed voxel
    highs = []  # 90th percentile around each seed
    for i, j, k in seeds:
        blk = a[
            max(0, k - rv[2]) : k + rv[2] + 1,
            max(0, j - rv[1]) : j + rv[1] + 1,
            max(0, i - rv[0]) : i + rv[0] + 1,
        ]
        vals.append(float(a[k, j, i]))
        highs.append(float(np.percentile(blk, 90)))
    img = to_sitk(a, v.geometry)
    ctx.report(0.1, "Region growing")
    lo = hi = 0.0
    if p["method"] in ("tol", "zakres"):
        if p["method"] == "tol":
            # grow over values similar to the clicked ones — no HU range to know beforehand
            lo, hi = min(vals) - p["tol"], max(max(vals), max(highs)) + p["tol"]
        else:
            lo, hi = sorted((p["lo"], p["hi"]))
        out = sitk.ConnectedThreshold(
            img, seedList=seeds, lower=float(lo), upper=float(hi), replaceValue=1
        )
    else:
        out = sitk.ConfidenceConnected(
            img,
            seedList=seeds,
            numberOfIterations=int(p["iterations"]),
            multiplier=float(p["multiplier"]),
            initialNeighborhoodRadius=1,
            replaceValue=1,
        )
    mask, _ = from_sitk(out)
    if not mask.any():
        shown = ", ".join(f"{x:g}" for x in vals[:3])
        why = f"poza zakresem {lo:g}–{hi:g}" if p["method"] == "zakres" else "nic podobnego wokół"
        raise GraphError(f"Pusty wynik: ziarno ma wartość {shown} — {why}")
    return {
        "out": _mask_out(
            ctx, mask > 0, v.geometry, _seg_info(f"Rozrost ({len(seeds)} ziaren)", _ref_of(v))
        )
    }


register(
    NodeType(
        id="segmentacja/rozrost",
        label="Region growing",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Rośnie od klikniętych ziaren po sąsiednich wokselach. Tolerancja: wartości podobne do ziaren "
        "(± próg); zakres: w przedziale [od, do]; adaptacyjny: według statystyki wokół ziaren.",
        inputs=(Port("in", "Wolumen", VOL),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param("seeds", "Ziarna", "points", []),
            Param(
                "method",
                "Metoda",
                "select",
                "tol",
                options=(("tol", "Tolerancja"), ("zakres", "Zakres"), ("adapt", "Adaptacyjny")),
            ),
            Param("tol", "±", "number", 150.0, min=1, max=2000, step=1, show_if=("method", "tol")),
            Param(
                "lo",
                "Od",
                "number",
                150.0,
                min=-5000,
                max=50000,
                step=1,
                show_if=("method", "zakres"),
            ),
            Param(
                "hi",
                "Do",
                "number",
                600.0,
                min=-5000,
                max=50000,
                step=1,
                show_if=("method", "zakres"),
            ),
            Param(
                "multiplier",
                "Mnożnik",
                "number",
                2.5,
                min=0.5,
                max=6,
                step=0.1,
                show_if=("method", "adapt"),
            ),
            Param(
                "iterations",
                "Iteracje",
                "int",
                3,
                min=0,
                max=10,
                step=1,
                show_if=("method", "adapt"),
            ),
        ),
        run=_rozrost,
        widget="seeds",
    )
)


# ── Edycja (pędzel / gumka) ──────────────────────────────────────────────────────


def _paint(mask: np.ndarray, g: Geometry, center: list[float], r_mm: float, value: int) -> None:
    """Ellipsoid in voxel space = sphere of radius r_mm in the world (anisotropic voxels)."""
    rel = np.asarray(center, dtype=np.float64) - np.asarray(g.origin)
    c = (g.matrix.T @ rel) / np.asarray(g.spacing)  # continuous (i, j, k)
    rv = np.asarray([r_mm / s for s in g.spacing])
    lo = np.maximum(0, np.floor(c - rv)).astype(int)
    hi = np.minimum(np.asarray(g.size) - 1, np.ceil(c + rv)).astype(int)
    if np.any(hi < lo):
        return
    ii = (np.arange(lo[0], hi[0] + 1) - c[0]) / max(rv[0], 1e-9)
    jj = (np.arange(lo[1], hi[1] + 1) - c[1]) / max(rv[1], 1e-9)
    kk = (np.arange(lo[2], hi[2] + 1) - c[2]) / max(rv[2], 1e-9)
    inside = (kk[:, None, None] ** 2 + jj[None, :, None] ** 2 + ii[None, None, :] ** 2) <= 1.0
    view = mask[lo[2] : hi[2] + 1, lo[1] : hi[1] + 1, lo[0] : hi[0] + 1]
    view[inside] = value


def _edycja(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    seg = _first(inputs, "in", SEG, required=False)
    vol = _first(inputs, "ref", VOL, required=False)
    if seg is not None:
        g, mask, ref = seg.geometry, seg.array().copy(), seg.info.get("ref", "")
    elif vol is not None:
        g, mask, ref = vol.geometry, np.zeros(vol.geometry.shape_kji, np.uint8), vol.ref
    else:
        raise GraphError("Podłącz segment do poprawy albo wolumen (pusty start)")
    n = sum(len(st["p"]) for st in p["strokes"]) or 1
    done = 0
    for st in p["strokes"]:
        value = 0 if st["mode"] == "erase" else 1
        for pt in st["p"]:
            _paint(mask, g, pt, st["r"], value)
            done += 1
            if done % 256 == 0:
                ctx.report(done / n, "Pędzel")
    return {
        "out": _mask_out(
            ctx,
            mask,
            g,
            # `strokes`: how many strokes this result contains — the views draw only the newer
            # ones as pending (instant feedback without double-drawing)
            _seg_info(f"Edycja ({len(p['strokes'])} pociągnięć)", ref, strokes=len(p["strokes"])),
        )
    }


register(
    NodeType(
        id="segmentacja/edycja",
        label="Edycja pędzlem",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Ręczna poprawka: pędzel dodaje, gumka usuwa (kule o promieniu w mm). Pociągnięcia są zapisane w "
        "node'zie — po zmianie wejścia nakładają się ponownie.",
        inputs=(
            Port("in", "Segment", SEG, optional=True),
            Port("ref", "Wolumen (pusty start)", VOL, optional=True),
        ),
        outputs=(Port("out", "Segment", SEG),),
        params=(Param("strokes", "Pociągnięcia", "strokes", []),),
        run=_edycja,
        widget="brush",
        version=2,  # info.strokes
    )
)


# ── Logika ─────────────────────────────────────────────────────────────────────

_OPS = {
    "or": (lambda a, b: a | b, "∪"),
    "and": (lambda a, b: a & b, "∩"),
    "sub": (lambda a, b: a & ~b, "−"),
    "xor": (lambda a, b: a ^ b, "⊕"),
}


def _logika(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    a = _first(inputs, "a", SEG)
    b = _first(inputs, "b", SEG)
    fn, sym = _OPS[p["op"]]
    out = fn(a.array() > 0, _on_grid(b, a.geometry) > 0)
    name = f"{a.info.get('name', 'A')} {sym} {b.info.get('name', 'B')}"
    return {"out": _mask_out(ctx, out, a.geometry, _seg_info(name, a.info.get("ref", "")))}


register(
    NodeType(
        id="segmentacja/logika",
        label="Logika",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Łączy dwa segmenty: suma (A ∪ B), część wspólna (A ∩ B), różnica (A − B), XOR. B jest dopasowywany do siatki A.",
        inputs=(Port("a", "A", SEG), Port("b", "B", SEG)),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "op",
                "Operacja",
                "select",
                "or",
                options=(("or", "∪"), ("and", "∩"), ("sub", "A−B"), ("xor", "⊕")),
            ),
        ),
        run=_logika,
    )
)


# ── Morfologia ─────────────────────────────────────────────────────────────────


def _morfologia(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", SEG)
    img = to_sitk((s.array() > 0).astype(np.uint8), s.geometry)
    rad = _radius_vox(s.geometry, p["radius"])
    op = p["op"]
    ctx.report(0.1, "Morfologia")
    if op == "fill":
        out = sitk.BinaryFillhole(img, fullyConnected=False, foregroundValue=1)
    elif not any(rad):
        out = img
    else:
        f = {
            "dilate": sitk.BinaryDilateImageFilter,
            "erode": sitk.BinaryErodeImageFilter,
            "open": sitk.BinaryMorphologicalOpeningImageFilter,
            "close": sitk.BinaryMorphologicalClosingImageFilter,
        }[op]()
        f.SetKernelRadius(rad)
        f.SetKernelType(sitk.sitkBall)
        f.SetForegroundValue(1)
        out = f.Execute(img)
    mask, _ = from_sitk(out)
    labels = {
        "dilate": "dylatacja",
        "erode": "erozja",
        "open": "otwarcie",
        "close": "zamknięcie",
        "fill": "wypełnienie",
    }
    return {
        "out": _mask_out(
            ctx,
            mask,
            s.geometry,
            _seg_info(
                f"{s.info.get('name', 'Segment')} · {labels[op]}",
                s.info.get("ref", ""),
                s.info.get("color", PALETTE[0]),
            ),
        )
    }


register(
    NodeType(
        id="segmentacja/morfologia",
        label="Morfologia",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Dylatacja (pogrubia), erozja (odchudza), otwarcie (usuwa drobne wypustki), zamknięcie (łata szczeliny), "
        "wypełnienie dziur (zamknięte jamy w środku).",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "op",
                "Operacja",
                "select",
                "close",
                options=(
                    ("dilate", "Dylatacja"),
                    ("erode", "Erozja"),
                    ("open", "Otwarcie"),
                    ("close", "Zamknięcie"),
                    ("fill", "Wypełnij dziury"),
                ),
            ),
            Param("radius", "Promień", "number", 1.0, min=0.1, max=15, step=0.1, unit="mm"),
        ),
        run=_morfologia,
    )
)


# ── Wyspy ──────────────────────────────────────────────────────────────────────


def _wyspy(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", SEG)
    img = to_sitk((s.array() > 0).astype(np.uint8), s.geometry)
    cc = sitk.ConnectedComponent(img, False)  # face connectivity (positional-only in SimpleITK)
    vox_mm3 = float(np.prod(s.geometry.spacing))
    if p["mode"] == "largest":
        rel = sitk.RelabelComponent(cc, sortByObjectSize=True)
        mask, _ = from_sitk(rel)
        mask = (mask >= 1) & (mask <= int(p["count"]))
        tag = f"{int(p['count'])} największ{'a' if int(p['count']) == 1 else 'e'}"
    else:
        min_vox = int(np.ceil(p["min_mm3"] / vox_mm3))
        rel = sitk.RelabelComponent(cc, minimumObjectSize=max(1, min_vox), sortByObjectSize=True)
        mask, _ = from_sitk(rel)
        mask = mask > 0
        tag = f"≥ {p['min_mm3']:g} mm³"
    return {
        "out": _mask_out(
            ctx,
            mask,
            s.geometry,
            _seg_info(
                f"{s.info.get('name', 'Segment')} · {tag}",
                s.info.get("ref", ""),
                s.info.get("color", PALETTE[0]),
            ),
        )
    }


register(
    NodeType(
        id="segmentacja/wyspy",
        label="Wyspy",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Usuwa drobne, niepołączone kawałki: zostaw N największych albo tylko te większe niż zadana objętość.",
        inputs=(Port("in", "Segment", SEG),),
        outputs=(Port("out", "Segment", SEG),),
        params=(
            Param(
                "mode",
                "Tryb",
                "select",
                "largest",
                options=(("largest", "Największe"), ("min", "Min. objętość")),
            ),
            Param("count", "Ile", "int", 1, min=1, max=50, step=1, show_if=("mode", "largest")),
            Param(
                "min_mm3",
                "Min.",
                "number",
                100.0,
                min=1,
                max=1e6,
                step=10,
                unit="mm³",
                show_if=("mode", "min"),
            ),
        ),
        run=_wyspy,
    )
)


# ── Złóż / Rozłóż ───────────────────────────────────────────────────────────────


def _zloz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    segs = [v for v in inputs.get("in") or [] if isinstance(v, VolumeValue) and v.kind == SEG]
    if not segs:
        raise GraphError("Podłącz co najmniej jeden segment")
    g = segs[0].geometry
    lab = np.zeros(g.shape_kji, np.uint8)
    table = []
    for n, s in enumerate(segs[:255], start=1):
        lab[_on_grid(s, g) > 0] = n  # later inputs win where segments overlap
        table.append(
            {
                "id": n,
                "name": s.info.get("name", f"Segment {n}"),
                "color": PALETTE[(n - 1) % len(PALETTE)],
            }
        )
    info = {
        "name": f"Segmentacja ({len(table)})",
        "ref": segs[0].info.get("ref", ""),
        "labels": table,
    }
    return {"out": ctx.volume_result(lab, g, info, kind=LAB)}


register(
    NodeType(
        id="segmentacja/zloz",
        label="Złóż",
        domain="segmentacja",
        stage="wynik",
        description="Łączy kilka segmentów w jedną segmentację (mapę etykiet) — każdy dostaje własny kolor.",
        inputs=(Port("in", "Segmenty", SEG, multi=True),),
        outputs=(Port("out", "Segmentacja", LAB),),
        params=(),
        run=_zloz,
    )
)


def _rozloz(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    s = _first(inputs, "in", LAB)
    lid = int(p["label"])
    entry = next(
        (e for e in s.info.get("labels", []) if e["id"] == lid),
        {"name": f"Etykieta {lid}", "color": PALETTE[0]},
    )
    mask = s.array() == lid
    return {
        "out": _mask_out(
            ctx, mask, s.geometry, _seg_info(entry["name"], s.info.get("ref", ""), entry["color"])
        )
    }


register(
    NodeType(
        id="segmentacja/rozloz",
        label="Rozłóż",
        domain="segmentacja",
        stage="przetwarzanie",
        description="Wyciąga jeden segment (etykietę) z segmentacji.",
        inputs=(Port("in", "Segmentacja", LAB),),
        outputs=(Port("out", "Segment", SEG),),
        params=(Param("label", "Etykieta", "int", 1, min=1, max=255, step=1),),
        run=_rozloz,
    )
)


# ── Import labelmapy ───────────────────────────────────────────────────────────


def _import(ctx: EvalContext, inputs: dict, p: dict) -> dict[str, Any]:
    v = ctx.source_volume(p["volume"], exact=True)  # labels must never be averaged: level 0
    a = v.array()
    if a.dtype.kind == "f" and not np.all(np.mod(a, 1) == 0):
        raise GraphError("To nie jest mapa etykiet (wartości niecałkowite)")
    ids = [int(x) for x in np.unique(a) if x > 0]
    if len(ids) > 255:
        raise GraphError(f"Za dużo etykiet ({len(ids)}) — maks. 255")
    lab = np.zeros(a.shape, np.uint8)
    names = {int(e["id"]): e["name"] for e in v.info.get("labels", [])}
    table = []
    for n, lid in enumerate(ids, start=1):
        lab[a == lid] = n
        table.append(
            {
                "id": n,
                "name": names.get(lid, f"Etykieta {lid}"),
                "color": PALETTE[(n - 1) % len(PALETTE)],
            }
        )
    ref = p.get("ref") or v.ref
    info = {"name": v.info.get("name", "Labelmapa"), "ref": ref, "labels": table}
    return {"out": ctx.volume_result(lab, v.geometry, info, kind=LAB)}


register(
    NodeType(
        id="segmentacja/import",
        label="Labelmapa",
        domain="segmentacja",
        stage="dane",
        description="Mapa etykiet z biblioteki (np. NIfTI z innego programu) jako segmentacja. Opcjonalnie wskaż obraz, "
        "na którym ma być pokazywana.",
        inputs=(),
        outputs=(Port("out", "Segmentacja", LAB),),
        params=(Param("volume", "Labelmapa", "volume", ""), Param("ref", "Tło", "volume", "")),
        run=_import,
    )
)
