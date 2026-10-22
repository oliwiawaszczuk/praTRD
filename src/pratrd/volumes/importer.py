"""Candidate → stored volume: decode/stream → level 0 → pyramid + stats → tags, thumbnail,
library entry. Runs inside a job; progress 0–0.8 is reading, 0.8–1 the pyramid."""

import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pydicom

from ..dicom import anonymize as anon
from ..dicom import tags as tagdump
from ..dicom.decode import FrameRef, decode_batch
from ..dicom.scan import Candidate
from ..jobs import Job
from ..jsonio import write_json
from . import decode_pool, store
from .files import iter_slabs
from .geometry import Geometry
from .library import Library

_BATCH_BYTES = 4 << 20  # per decode batch; 2×workers in flight ≈ 50 MB (16 MB: same speed, +80 MB)
_INLINE_FRAMES = 32  # smaller series decode in-thread: no pool start-up for tiny data
_THUMB_EDGE = 160

_PLANE = {0: "strzałkowy", 1: "czołowy", 2: "osiowy"}  # dominant LPS component of the normal


def plane_names(geom: Geometry) -> dict[str, str]:
    """Anatomical name of the slice plane perpendicular to each index axis."""
    d = geom.matrix
    return {axis: _PLANE[int(np.argmax(np.abs(d[:, col])))] for col, axis in enumerate("ijk")}


def _default_window(cand: Candidate, stats: dict[str, Any]) -> dict[str, float]:
    w = cand.info.get("window")
    if w:
        return w
    lo, hi = stats["p1"], stats["p99"]
    if hi <= lo:
        lo, hi = stats["min"], stats["max"]
    return {"center": (lo + hi) / 2, "width": max(hi - lo, 1e-6)}


def _read_dicom(job: Job, cand: Candidate, writer: store.VolumeWriter) -> None:
    stack = cand.stack
    assert stack is not None
    refs: list[FrameRef] = [(f.path, f.index, f.slope, f.intercept) for f in stack.frames]
    nk = len(refs)
    frame_bytes = cand.geometry.size[0] * cand.geometry.size[1] * cand.dtype.itemsize
    per_batch = max(1, min(32, _BATCH_BYTES // max(frame_bytes, 1)))
    batches = [(refs[i : i + per_batch], cand.dtype.str, cand.rgb) for i in range(0, nk, per_batch)]

    def on_result(_: int, slab: np.ndarray) -> None:
        writer.append(slab)
        job.report(0.8 * writer.written / nk, f"Warstwy {writer.written}/{nk}")

    if nk <= _INLINE_FRAMES:
        for b in batches:
            on_result(0, decode_batch(*b))
        return
    decode_pool.ordered_map(
        decode_batch,
        batches,
        in_flight=2 * decode_pool.workers(),
        on_result=on_result,
        should_stop=lambda: job.cancelled,
    )
    job.check()


def _read_file(job: Job, cand: Candidate, writer: store.VolumeWriter) -> None:
    nk = cand.geometry.size[2]
    for slab in iter_slabs(cand.file_path, cand.kind, store.CHUNK):
        writer.append(slab)
        job.report(0.8 * writer.written / nk, f"Warstwy {writer.written}/{nk}")


def _thumbnail(path: Path, meta: dict[str, Any], window: dict[str, float], out: Path) -> None:
    from PIL import Image

    levels = meta["levels"]
    level = 0
    for n, g in enumerate(levels):
        if max(g["size"][0], g["size"][1]) >= _THUMB_EDGE:
            level = n
    nk = levels[level]["size"][2]
    img = store.read_slice(path, level, "k", nk // 2).astype(np.float32)
    lo = window["center"] - window["width"] / 2
    u8 = np.clip((img - lo) * (255.0 / window["width"]), 0, 255).astype(np.uint8)
    sp = levels[level]["spacing"]
    h, w = u8.shape
    # Physical aspect ratio (pixels may be non-square).
    ph, pw = h * sp[1], w * sp[0]
    scale = _THUMB_EDGE / max(ph, pw)
    size = (max(1, round(pw * scale)), max(1, round(ph * scale)))
    Image.fromarray(u8).resize(size, Image.Resampling.BILINEAR).save(out, optimize=True)


def import_candidate(
    job: Job, root: Path, ws_dir: Path, library: Library, cand: Candidate, anonymize: bool
) -> dict[str, Any]:
    vid = uuid.uuid4().hex[:12]
    t0 = time.monotonic()
    path = Library.volume_path(ws_dir, vid)
    is_seg = cand.kind == "seg"
    seg_labels: list[dict] = []
    writer = store.VolumeWriter(path, cand.geometry, cand.dtype, label=is_seg)
    try:
        if cand.kind == "dicom":
            _read_dicom(job, cand, writer)
        elif is_seg:
            from .files import read_seg

            arr, _, seg_labels = read_seg(cand.file_path)
            writer.append(arr)
        else:
            _read_file(job, cand, writer)
        job.report(0.8, "Piramida rozdzielczości i statystyki…")
        meta = writer.finish(
            lambda p: job.report(0.8 + 0.2 * p),
            {"source": cand.kind, "planes": plane_names(cand.geometry)},
        )
    except BaseException:
        writer.abort()
        raise

    window = _default_window(cand, meta["stats"])
    sdir = Library.series_dir(ws_dir, vid)
    sdir.mkdir(parents=True, exist_ok=True)
    try:
        _thumbnail(path, meta, window, sdir / "thumb.png")
    except Exception:  # noqa: BLE001 — a missing thumbnail must not fail the import
        pass

    info = dict(cand.info)
    if cand.kind == "dicom":
        ds = pydicom.dcmread(cand.header_path, stop_before_pixels=True)
        if anonymize:
            anon.anonymize_dataset(ds)
        write_json(sdir / "tags.json", tagdump.dump(ds))
    if anonymize:
        info["patientName"] = anon.pseudonym(
            root, info.get("patientId", ""), info.get("patientName", "")
        )
        info["patientId"] = ""
        info["studyDate"] = ""
    info.pop("window", None)

    entry = {
        "id": vid,
        "name": cand.name,
        "kind": "labelmap" if is_seg else "scalar",
        **({"labels": seg_labels} if is_seg else {}),
        "source": cand.kind,
        "sourcePath": None if anonymize else (cand.file_path or str(Path(cand.header_path).parent)),
        "fingerprint": cand.fingerprint,
        "anonymized": anonymize,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "size": list(cand.geometry.size),
        "spacing": list(cand.geometry.spacing),
        "dtype": cand.dtype.name,
        "levels": len(meta["levels"]),
        "bytesOnDisk": sum(f.stat().st_size for f in path.rglob("*") if f.is_file()),
        "window": window,
        "stats": {k: meta["stats"][k] for k in ("min", "max", "p1", "p99")},
        "planes": meta["planes"],
        "warnings": cand.warnings,
        "importSeconds": round(time.monotonic() - t0, 2),
        **info,
    }
    library.add(ws_dir, entry)
    return {"vid": vid, "name": cand.name}
