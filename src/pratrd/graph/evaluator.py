"""Graph evaluation: upstream closure of the targets, topological order, content-addressed
cache, live per-node events.

Cache key of a node = sha256(type, algorithm version, cleaned params, keys of its inputs in
socket/edge order). Only SOURCE nodes depend on the quality (they pick the pyramid level),
so when preview and full resolution use the same level they share every downstream result.
Results persist across sessions: cache/<key>.json (manifest) + cache/<key>.zarr (voxels).
"""

import hashlib
import json
import os
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ..events import EventHub
from ..jobs import Job
from ..jsonio import read_json, write_json
from ..meshes import store as mesh_store
from ..volumes import store
from ..volumes.geometry import Geometry
from ..volumes.importer import plane_names
from ..volumes.library import Library
from .types import REGISTRY, NodeType
from .values import ARRAYS, DataValue, MeshValue, VolumeValue

Quality = Literal["preview", "full"]

PREVIEW_VOXELS = 16 << 20  # ≈ 256³: every light op stays well under a second
_MEMO_MAX = 512


class GraphError(Exception):
    pass


@dataclass
class NodeSpec:
    id: str
    type: NodeType
    params: dict[str, Any]


class EvalContext:
    """What a node's run() may use: inputs come as arguments, everything else from here."""

    def __init__(
        self, ev: "Evaluator", node: NodeSpec, key: str, job: Job, span: tuple[float, float]
    ):
        self._ev = ev
        self.node = node
        self.key = key
        self.job = job
        self.quality = ev.quality
        self._span = span

    def report(self, fraction: float, message: str | None = None) -> None:
        """In-node progress (0..1); also the cancellation point for long operations."""
        a, b = self._span
        self.job.report(a + (b - a) * min(max(fraction, 0.0), 1.0), message)

    def source_volume(self, vid: str, exact: bool = False) -> VolumeValue:
        """exact=True: always level 0 (e.g. label maps, which a pyramid would average)."""
        return self._ev.source_volume(vid, exact)

    def volume_by_ref(self, ref: str) -> VolumeValue:
        """Any volume by id — e.g. the background a segment was derived from (`info.ref`)."""
        return self._ev.volume_by_ref(ref)

    def volume_result(
        self,
        arr: np.ndarray,
        g: Geometry,
        info: dict[str, Any],
        socket: str = "out",
        kind: str = "wolumen",
    ) -> VolumeValue:
        """Persist an output volume (multiscale, so viewports get LOD for free).
        kind "segment"/"segmentacja" → label map (uint8, max-pyramid, voxel census)."""
        ref = self.key if socket == "out" else _hash24(self.key + "|" + socket)
        path = self._ev.ws_dir / "cache" / f"{ref}.zarr"
        label = kind != "wolumen"
        arr = np.ascontiguousarray(arr)
        if path.is_dir():
            if label:  # same key = same voxels: the census stored with the result
                saved = store.read_meta(path).get("info", {})
                info = saved if "voxels" in saved else {**info, **label_stats(arr, g)}
        else:
            w = store.VolumeWriter(path, g, arr.dtype, label=label)

            def attrs(stats: dict[str, Any]) -> dict[str, Any]:
                nonlocal info
                if label:  # the writer's histogram IS the label census — no second pass
                    counts = {int(k): int(c) for k, c in stats.get("labels", {}).items()}
                    info = {**info, **census(counts, g)}
                return {"source": "node", "info": info, "planes": plane_names(g)}

            try:
                w.append(arr)
                w.finish(lambda p: None, attrs)
            except BaseException:
                w.abort()
                raise
        # the next node reads this result from memory, not by decoding what was just written
        ARRAYS.put(path, 0, arr)
        return VolumeValue(ref=ref, path=path, level=0, geometry=g, info=info, kind=kind)

    def mesh_result(
        self, verts: np.ndarray, faces: np.ndarray, info: dict[str, Any], socket: str = "out"
    ) -> MeshValue:
        """Persist an output surface (world LPS mm); its stats (area, volume, closed) join
        `info`. The next node gets the arrays from memory."""
        ref = self.key if socket == "out" else _hash24(self.key + "|" + socket)
        path = self._ev.ws_dir / "cache" / f"{ref}.mesh"
        if path.is_dir():
            meta = mesh_store.read_meta(path)
        else:
            meta = mesh_store.write_mesh(path, verts, faces, info)
        v = np.ascontiguousarray(verts, dtype=np.float32)
        mesh_store.MESHES.put(path, v, np.ascontiguousarray(faces, dtype=np.int64))
        return MeshValue(ref=ref, path=path, info=mesh_info(meta))

    def library_mesh(self, mid: str) -> MeshValue:
        """A mesh imported into the workspace (Dane / node "Plik mesha")."""
        if not mid:
            raise GraphError("Nie wybrano pliku mesha")
        path = mesh_store.mesh_path(self._ev.ws_dir, mid)
        if not path.is_dir():
            raise GraphError("Mesh nie istnieje w bibliotece — wczytaj plik ponownie")
        return MeshValue(ref=mid, path=path, info=mesh_info(mesh_store.read_meta(path)))


def mesh_info(meta: dict[str, Any]) -> dict[str, Any]:
    """What node cards / viewports need about a mesh (info + counts + stats)."""
    return {**meta.get("info", {}), "verts": meta["verts"], "faces": meta["faces"], **meta["stats"]}


_COUNT_PIECE = 1 << 24  # voxels per bincount call (bincount copies its input to intp)


def census(counts: dict[int, int], g: Geometry) -> dict[str, Any]:
    """{label: voxels} → what node cards and measurements show (voxels, ml, per label)."""
    vox_ml = float(np.prod(g.spacing)) / 1000.0
    labels = {
        str(i): {"voxels": c, "ml": round(c * vox_ml, 3)}
        for i, c in sorted(counts.items())
        if i and c
    }
    total = sum(c for i, c in counts.items() if i)
    return {"voxels": total, "ml": round(total * vox_ml, 3), "labelStats": labels}


def label_stats(arr: np.ndarray, g: Geometry) -> dict[str, Any]:
    """Census counted from the voxels (fallback for results cached without one). In pieces:
    one bincount over a 512²×2000 mask needed a 4 GB intp copy."""
    counts = np.zeros(2, np.int64)
    if arr.dtype.kind in "ui":
        flat = arr.reshape(-1)
        for p in range(0, flat.size, _COUNT_PIECE):
            c = np.bincount(flat[p : p + _COUNT_PIECE])
            if c.size > counts.size:
                counts = np.pad(counts, (0, c.size - counts.size))
            counts[: c.size] += c
    return census({i: int(c) for i, c in enumerate(counts) if c}, g)


VOLUME_KINDS = frozenset({"wolumen", "segment", "segmentacja"})
DATA_KINDS = frozenset({"punkty", "tabela"})
MESH_KIND = "mesh"


def _hash24(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def value_from_json(ws_dir: Path, d: dict[str, Any]) -> Any:
    # every volume-like kind (segments too) — a cached segment must come back as a
    # VolumeValue, or nodes downstream of it get nothing after a restart
    if d.get("kind") in VOLUME_KINDS:
        return VolumeValue(
            ref=d["ref"],
            path=Library.volume_path(ws_dir, d["ref"]),
            level=int(d["level"]),
            geometry=Geometry.from_json(d["geometry"]),
            info=d.get("info", {}),
            kind=d["kind"],
        )
    if d.get("kind") == MESH_KIND:
        return MeshValue(
            ref=d["ref"], path=mesh_store.mesh_path(ws_dir, d["ref"]), info=d.get("info", {})
        )
    if d.get("kind") in DATA_KINDS:
        return DataValue(d["kind"], d.get("value"))
    return d.get("value")


def value_to_json(v: Any) -> dict[str, Any]:
    if hasattr(v, "to_json"):
        return v.to_json()
    return {"kind": "liczba" if isinstance(v, (int, float)) else "json", "value": v}


class Evaluator:
    """One per workspace. Thread-safety: evaluations run on the single `graph` job lane."""

    def __init__(self, wid: str, ws_dir: Path, library: Library, hub: EventHub) -> None:
        self.wid = wid
        self.ws_dir = ws_dir
        self.library = library
        self.hub = hub
        self.quality: Quality = "preview"
        self._memo: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    # ── sources ────────────────────────────────────────────────────────────────
    def source_volume(self, vid: str, exact: bool = False) -> VolumeValue:
        if not vid:
            raise GraphError("Nie wybrano serii")
        entry = self.library.get(self.ws_dir, vid)
        path = self.library.volume_path(self.ws_dir, vid)
        meta = store.read_meta(path)
        level = 0
        if self.quality == "preview" and not exact:
            for L, g in enumerate(meta["levels"]):
                level = L
                if int(np.prod(g["size"])) <= PREVIEW_VOXELS:
                    break
        info = {
            "name": entry["name"],
            "modality": entry.get("modality", ""),
            "window": entry["window"],
            "sourceVid": vid,
        }
        if entry.get("labels"):
            info["labels"] = entry["labels"]  # e.g. segment names of an imported DICOM-SEG
        return VolumeValue(
            ref=vid,
            path=path,
            level=level,
            geometry=Geometry.from_json(meta["levels"][level]),
            info=info,
        )

    def volume_by_ref(self, ref: str) -> VolumeValue:
        if len(ref) == 12:
            return self.source_volume(ref)
        path = self.library.volume_path(self.ws_dir, ref)
        if not path.is_dir():
            raise GraphError("Brak wolumenu tła — przelicz graf")
        meta = store.read_meta(path)
        return VolumeValue(
            ref=ref,
            path=path,
            level=0,
            geometry=Geometry.from_json(meta["levels"][0]),
            info=meta.get("info", {}),
        )

    # ── evaluation ─────────────────────────────────────────────────────────────
    def evaluate(
        self, job: Job, gid: str, graph: dict[str, Any], targets: list[str], quality: Quality
    ) -> dict[str, Any]:
        self.quality = quality
        nodes, inputs = self._parse(graph)
        order = self._order(nodes, inputs, [t for t in targets if t in nodes])
        keys: dict[str, str] = {}
        values: dict[str, dict[str, Any]] = {}
        failed: set[str] = set()
        results: dict[str, Any] = {}

        def emit(nid: str, state: str, **extra: Any) -> None:
            self.hub.publish(
                {
                    "type": "graph-node",
                    "wid": self.wid,
                    "gid": gid,
                    "quality": quality,
                    "node": nid,
                    "state": state,
                    **extra,
                }
            )

        n = max(len(order), 1)
        for idx, nid in enumerate(order):
            job.check()
            spec = nodes[nid]
            # inputs: per socket, upstream (node, socket) in edge order
            ins: dict[str, list[Any]] = {}
            in_keys: list[Any] = []
            blocked = ""
            for port in spec.type.inputs:
                srcs = inputs.get((nid, port.id), [])
                if not srcs and not port.multi and not port.optional:
                    blocked = f"Brak wejścia: {port.label}"
                vals = []
                for src_node, src_socket in srcs:
                    if src_node in failed or src_node not in values:
                        blocked = blocked or "Błąd wyżej w grafie"
                        continue
                    vals.append(values[src_node].get(src_socket))
                    in_keys.append([port.id, keys[src_node], src_socket])
                ins[port.id] = vals
            if blocked:
                failed.add(nid)
                emit(nid, "blocked", error=blocked)
                results[nid] = {"state": "blocked", "error": blocked}
                continue

            params = spec.params
            key_src = [spec.type.id, spec.type.version, params, in_keys]
            if not spec.type.inputs:  # sources: the chosen level is part of the identity
                key_src.append(quality)
            key = _hash24(json.dumps(key_src, sort_keys=True, default=str))
            keys[nid] = key

            cached = self._lookup(key)
            if cached is not None:
                values[nid] = cached
                out_json = {s: value_to_json(v) for s, v in cached.items()}
                emit(nid, "done", outputs=out_json, cached=True)
                results[nid] = {"state": "done", "outputs": out_json}
                continue

            emit(nid, "computing")
            span = (idx / n, (idx + 1) / n)
            job.report(span[0], spec.type.label)
            t0 = time.monotonic()
            try:
                out = spec.type.run(EvalContext(self, spec, key, job, span), ins, params)
            except Exception as e:  # noqa: BLE001 — one bad node must not kill the graph
                from ..jobs import Cancelled

                if isinstance(e, Cancelled):
                    emit(nid, "stale")
                    raise
                failed.add(nid)
                msg = str(e) or type(e).__name__
                emit(nid, "error", error=msg)
                results[nid] = {"state": "error", "error": msg}
                continue
            values[nid] = out
            out_json = {s: value_to_json(v) for s, v in out.items()}
            if spec.type.inputs:  # sources only point at library data: nothing to persist
                self._store(key, out_json)
            self._remember(key, out)
            ms = round((time.monotonic() - t0) * 1000)
            emit(nid, "done", outputs=out_json, ms=ms)
            results[nid] = {"state": "done", "outputs": out_json, "ms": ms}
        return results

    def _parse(
        self, graph: dict[str, Any]
    ) -> tuple[dict[str, NodeSpec], dict[tuple[str, str], list[tuple[str, str]]]]:
        nodes: dict[str, NodeSpec] = {}
        for raw in graph.get("nodes", []):
            nt = REGISTRY.get(raw.get("type", ""))
            if nt is None:
                continue  # unknown (e.g. from a newer version): treated as absent
            nodes[str(raw["id"])] = NodeSpec(str(raw["id"]), nt, nt.clean_params(raw.get("params")))
        inputs: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for e in graph.get("edges", []):
            src, dst = nodes.get(str(e.get("from"))), nodes.get(str(e.get("to")))
            if not src or not dst:
                continue
            out = next((p for p in src.type.outputs if p.id == e.get("fromSocket")), None)
            inp = next((p for p in dst.type.inputs if p.id == e.get("toSocket")), None)
            if not out or not inp or out.kind != inp.kind:
                continue  # strict typing: kinds must match exactly
            lst = inputs.setdefault((dst.id, inp.id), [])
            if inp.multi or not lst:
                lst.append((src.id, out.id))
        return nodes, inputs

    def _order(self, nodes: dict[str, NodeSpec], inputs: dict, targets: list[str]) -> list[str]:
        ups: dict[str, list[str]] = {nid: [] for nid in nodes}
        for (dst, _), srcs in inputs.items():
            ups[dst].extend(s for s, _ in srcs)
        order: list[str] = []
        state: dict[str, int] = {}  # 1 visiting, 2 done

        def visit(nid: str) -> None:
            st = state.get(nid)
            if st == 2:
                return
            if st == 1:
                raise GraphError("Graf zawiera cykl")
            state[nid] = 1
            for u in ups[nid]:
                visit(u)
            state[nid] = 2
            order.append(nid)

        for t in targets:
            visit(t)
        return order

    # ── cache ──────────────────────────────────────────────────────────────────
    def _manifest(self, key: str) -> Path:
        return self.ws_dir / "cache" / f"{key}.json"

    def _lookup(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None:
                self._memo.move_to_end(key)
                return hit
        m = read_json(self._manifest(key), None)
        if not isinstance(m, dict):
            return None
        out = {s: value_from_json(self.ws_dir, d) for s, d in m["outputs"].items()}
        if any(
            isinstance(v, (VolumeValue, MeshValue)) and not v.path.is_dir() for v in out.values()
        ):
            return None
        os.utime(self._manifest(key))  # LRU age for pruning
        self._remember(key, out)
        return out

    def _remember(self, key: str, out: dict[str, Any]) -> None:
        with self._lock:
            self._memo[key] = out
            while len(self._memo) > _MEMO_MAX:
                self._memo.popitem(last=False)

    def _store(self, key: str, out_json: dict[str, Any]) -> None:
        size = 0
        for d in out_json.values():
            if d.get("kind") in ("wolumen", "segment", "segmentacja"):
                p = Library.volume_path(self.ws_dir, d["ref"])
                size += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            elif d.get("kind") == MESH_KIND:
                size += mesh_store.disk_bytes(mesh_store.mesh_path(self.ws_dir, d["ref"]))
        write_json(
            self._manifest(key), {"outputs": out_json, "bytes": size, "created": time.time()}
        )

    def prune(self, budget_bytes: int, keep: set[str] = frozenset()) -> int:  # type: ignore[assignment]
        """Delete least-recently-used results until the cache fits the budget."""
        entries = []
        for m in (self.ws_dir / "cache").glob("*.json"):
            d = read_json(m, None)
            if isinstance(d, dict):
                entries.append((m.stat().st_mtime, m.stem, int(d.get("bytes", 0)), d))
        total = sum(e[2] for e in entries)
        removed = 0
        for _, key, size, d in sorted(entries):
            if total <= budget_bytes:
                break
            if key in keep:
                continue
            for out in d.get("outputs", {}).values():
                if out.get("kind") in ("wolumen", "segment", "segmentacja"):
                    p = Library.volume_path(self.ws_dir, out["ref"])
                    store.forget(p)
                    ARRAYS.forget(p)
                    shutil.rmtree(p, ignore_errors=True)
                elif out.get("kind") == MESH_KIND and len(out.get("ref", "")) == 24:
                    p = mesh_store.mesh_path(self.ws_dir, out["ref"])
                    mesh_store.MESHES.forget(p)
                    shutil.rmtree(p, ignore_errors=True)
            self._manifest(key).unlink(missing_ok=True)
            with self._lock:
                self._memo.pop(key, None)
            total -= size
            removed += 1
        return removed
