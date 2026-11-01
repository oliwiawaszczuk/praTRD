"""Running a user node's Python code inside the sidecar.

The code sees a small facade instead of the internal API:
    def run(inputs, params, ctx):  ->  {output_id: value}  (or the value itself for one output)
`inputs.<id>` = Volume / Mesh / table dict / list of points / float (list for multi inputs),
`params.<key>` = cleaned parameter. Plain results are wrapped by the declared output kind:
ndarray → volume on the grid of the input with the same shape (bool → segment),
(verts, faces) → mesh, list of dicts → table, number → liczba, [[x, y, z], …] → punkty.

The module is compiled lazily on first use (startup only reads manifests), its source is
registered in linecache, and errors are reported with the line in the user's code.
"""

import builtins
import contextlib
import linecache
import math
import threading
import time
import traceback
import warnings
from typing import Any

import numpy as np

from ..graph.evaluator import EvalContext, GraphError
from ..graph.values import DataValue, MeshValue, VolumeValue
from ..jobs import Cancelled
from ..volumes.geometry import Geometry

VOLUME_KINDS = ("wolumen", "segment", "segmentacja")
# what the viewports can display (slices.ts); anything else is converted
_DTYPES = {"int16", "uint16", "int32", "uint8", "float32"}
_LOG_MAX = 200


class CodeError(Exception):
    """An error located in the user's code: `line` is 1-based (None = not in their code)."""

    def __init__(self, message: str, line: int | None = None, trace: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.trace = trace
        self.module: str | None = None  # a missing import (→ "install" in the test panel)


# ── facade passed to run() ──────────────────────────────────────────────────────


class Volume:
    """Volume on an input: `array` is read-only [k, j, i] (copy before writing)."""

    __slots__ = ("_v",)

    def __init__(self, v: VolumeValue) -> None:
        self._v = v

    @property
    def array(self) -> np.ndarray:
        return self._v.array()

    @property
    def kind(self) -> str:
        return self._v.kind

    @property
    def shape(self) -> tuple[int, int, int]:
        return self._v.geometry.shape_kji

    @property
    def spacing(self) -> tuple[float, float, float]:
        """mm per voxel along (i, j, k) = (columns, rows, slices)."""
        return self._v.geometry.spacing

    @property
    def spacing_kji(self) -> tuple[float, float, float]:
        """mm per voxel in array order — e.g. for scipy.ndimage `sampling=`."""
        s = self._v.geometry.spacing
        return (s[2], s[1], s[0])

    @property
    def origin(self) -> tuple[float, float, float]:
        return self._v.geometry.origin

    @property
    def direction(self) -> np.ndarray:
        return self._v.geometry.matrix

    @property
    def geometry(self) -> Geometry:
        return self._v.geometry

    @property
    def voxel_ml(self) -> float:
        return float(np.prod(self._v.geometry.spacing)) / 1000.0

    @property
    def info(self) -> dict[str, Any]:
        return dict(self._v.info)

    @property
    def name(self) -> str:
        return str(self._v.info.get("name", ""))

    @property
    def labels(self) -> list[dict[str, Any]]:
        return list(self._v.info.get("labels", []))

    def to_mm(self, ijk: Any) -> np.ndarray:
        """Voxel index (i, j, k) → world LPS mm."""
        g = self._v.geometry
        return np.asarray(g.origin) + g.matrix @ (np.asarray(g.spacing) * np.asarray(ijk, float))

    def to_ijk(self, xyz: Any) -> np.ndarray:
        """World LPS mm → (fractional) voxel index (i, j, k)."""
        g = self._v.geometry
        return (g.matrix.T @ (np.asarray(xyz, float) - np.asarray(g.origin))) / np.asarray(
            g.spacing
        )

    def __repr__(self) -> str:
        return f"Volume({self.kind}, shape={self.shape}, spacing={self.spacing})"


class Mesh:
    """Surface on an input: `verts` float32 [N, 3] in world LPS mm, `faces` int64 [M, 3]."""

    __slots__ = ("_m",)

    def __init__(self, m: MeshValue) -> None:
        self._m = m

    @property
    def verts(self) -> np.ndarray:
        return self._m.arrays()[0]

    @property
    def faces(self) -> np.ndarray:
        return self._m.arrays()[1]

    @property
    def info(self) -> dict[str, Any]:
        return dict(self._m.info)

    def __repr__(self) -> str:
        return f"Mesh(verts={self._m.info.get('verts')}, faces={self._m.info.get('faces')})"


class Ns:
    """`inputs.ct` and `inputs["ct"]` both work; a typo names the available keys."""

    def __init__(self, what: str, values: dict[str, Any]) -> None:
        object.__setattr__(self, "_what", what)
        object.__setattr__(self, "_values", values)

    def __getattr__(self, k: str) -> Any:
        try:
            return self._values[k]
        except KeyError:
            raise AttributeError(
                f"{self._what}.{k} nie istnieje (dostępne: {', '.join(self._values) or 'brak'})"
            ) from None

    def __getitem__(self, k: str) -> Any:
        return self.__getattr__(k)

    def __contains__(self, k: str) -> bool:
        return k in self._values

    def __iter__(self):  # noqa: ANN204
        return iter(self._values)

    def get(self, k: str, default: Any = None) -> Any:
        return self._values.get(k, default)

    def __setattr__(self, k: str, v: Any) -> None:
        raise AttributeError(f"{self._what} jest tylko do odczytu")

    def __repr__(self) -> str:
        return f"{self._what}({', '.join(f'{k}={v!r}' for k, v in self._values.items())})"


class Out:
    """Explicit result built with ctx.volume / ctx.mesh / ctx.table."""

    __slots__ = ("kind", "data", "opts")

    def __init__(self, kind: str, data: Any, **opts: Any) -> None:
        self.kind = kind
        self.data = data
        self.opts = opts


class Context:
    def __init__(self, ctx: EvalContext, rt: "Runtime") -> None:
        self._ctx = ctx
        self._rt = rt

    @property
    def quality(self) -> str:
        """ "preview" (downsampled data) or "full"."""
        return self._ctx.quality

    @property
    def preview(self) -> bool:
        return self._ctx.quality == "preview"

    @property
    def raw(self) -> EvalContext:
        """The internal context (volume_result, mesh_result…) — for advanced use."""
        return self._ctx

    def progress(self, fraction: float, message: str | None = None) -> None:
        """Progress 0..1 on the card; also where a cancelled run stops."""
        self._ctx.report(fraction, message)

    def volume(
        self,
        arr: Any,
        like: Any = None,
        grid: Geometry | None = None,
        name: str | None = None,
        window: tuple[float, float] | None = None,
        color: str | None = None,
        labels: list[Any] | None = None,
    ) -> Out:
        """Volume/segment/label map with explicit settings: `like` = input whose grid to
        use (when the shape matches several or none), `grid` = own grid (ctx.grid), `window`
        = (center, width), `labels` = names (or {name, color}) for labels 1..N."""
        return Out(
            "volume",
            arr,
            like=like,
            grid=grid,
            name=name,
            window=window,
            color=color,
            labels=labels,
        )

    def grid(
        self, like: Volume, spacing: Any = None, origin: Any = None, shape: Any = None
    ) -> Geometry:
        """Grid derived from an input (e.g. after resampling): spacing (i,j,k) mm, origin
        LPS mm, shape [k, j, i]."""
        g = like.geometry
        size = (int(shape[2]), int(shape[1]), int(shape[0])) if shape is not None else g.size
        sp = spacing if spacing is not None else g.spacing
        org = origin if origin is not None else g.origin
        return Geometry(
            size=size,  # type: ignore[arg-type]
            spacing=tuple(float(x) for x in sp),  # type: ignore[arg-type]
            origin=tuple(float(o) for o in org),  # type: ignore[arg-type]
            direction=g.direction,
        )

    def mesh(
        self, verts: Any, faces: Any, name: str | None = None, color: str | None = None
    ) -> Out:
        return Out("mesh", (verts, faces), name=name, color=color)

    def table(
        self,
        rows: list[dict[str, Any]],
        columns: list[Any] | None = None,
        chart: str | None = None,
        title: str = "",
    ) -> Out:
        """columns: keys, or (key, label, unit); chart: "bars" | "histogram" | "line"
        (x = first column, y = second)."""
        return Out("tabela", rows, columns=columns, chart=chart, title=title)


# ── runtime: one per node definition ────────────────────────────────────────────


class Runtime:
    def __init__(self, slug: str, manifest: dict[str, Any], code: str, test: bool = False):
        self.slug = slug
        self.manifest = manifest
        self.code = code
        self.filename = f"<wlasny:{slug}>"
        self.test = test
        self._module: dict[str, Any] | None = None
        self._lock = threading.Lock()
        # test mode only: what the creator's test panel shows
        self.logs: list[str] = []
        self.stats: dict[str, dict[str, Any]] = {}
        self.checks: list[dict[str, Any]] = []
        self.error: CodeError | None = None
        self.ms = 0

    # module ------------------------------------------------------------------
    def _print(self, *args: Any, sep: str = " ", end: str = "\n", **_: Any) -> None:
        if len(self.logs) < _LOG_MAX:
            self.logs.append(sep.join(str(a) for a in args) + ("" if end == "\n" else end))
        elif len(self.logs) == _LOG_MAX:
            self.logs.append("… (dalsze wydruki pominięte)")

    def module(self) -> dict[str, Any]:
        with self._lock:
            if self._module is None:
                self._module = self._load()
            return self._module

    def _load(self) -> dict[str, Any]:
        lines = self.code.splitlines(keepends=True)
        linecache.cache[self.filename] = (len(self.code), None, lines, self.filename)
        try:
            compiled = compile(self.code, self.filename, "exec")
        except SyntaxError as e:
            raise CodeError(f"Błąd składni: {e.msg}", e.lineno) from None
        ns: dict[str, Any] = {
            "__name__": f"pratrd_wlasne_{self.slug}",
            "__builtins__": builtins,
            "print": self._print,
            "np": np,
        }
        try:
            exec(compiled, ns)  # noqa: S102 — the user's own node, in their own app
        except Exception as e:  # noqa: BLE001
            raise self._located(e) from None
        if not callable(ns.get("run")):
            raise CodeError("Brak funkcji run(inputs, params, ctx)")
        return ns

    def check_code(self) -> CodeError | None:
        """Compile only (no exec) — instant feedback while typing."""
        try:
            compile(self.code, self.filename, "exec")
        except SyntaxError as e:
            return CodeError(f"Błąd składni: {e.msg}", e.lineno)
        return None

    def _located(self, e: BaseException) -> CodeError:
        frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename == self.filename]
        line = frames[-1].lineno if frames else None
        msg = f"{type(e).__name__}: {e}"
        if isinstance(e, ValueError) and "read-only" in str(e):
            msg += " — dane wejściowe są tylko do odczytu, użyj .copy()"
        module = None
        if isinstance(e, ModuleNotFoundError) and e.name:
            module = e.name.split(".")[0]
            msg += " — doinstaluj w panelu Biblioteki"
        trace = "".join(traceback.format_list(frames))
        err = CodeError(f"Linia {line}: {msg}" if line else msg, line, trace)
        err.module = module
        return err

    # run -----------------------------------------------------------------------
    def __call__(self, ctx: EvalContext, inputs: dict[str, list[Any]], p: dict) -> dict:
        try:
            return self._run(ctx, inputs, p)
        except CodeError as e:
            self.error = e
            raise GraphError(e.message) from None

    def _run(self, ctx: EvalContext, inputs: dict[str, list[Any]], p: dict) -> dict:
        m = self.manifest
        ns = self.module()
        in_vals: dict[str, Any] = {}
        for port in m["inputs"]:
            vals = [wrap_input(v) for v in inputs.get(port["id"]) or [] if v is not None]
            in_vals[port["id"]] = vals if port["multi"] else (vals[0] if vals else None)
        ins = Ns("inputs", in_vals)
        params = Ns("params", dict(p))
        t0 = time.monotonic()
        # warnings (e.g. numpy "divide by zero") go to the test console; catch_warnings is
        # process-global, but tests run alone on the graph lane
        guard = warnings.catch_warnings(record=True) if self.test else contextlib.nullcontext()
        with guard as caught:
            if caught is not None:
                warnings.simplefilter("always")
            try:
                res = ns["run"](ins, params, Context(ctx, self))
            except (Cancelled, GraphError):
                raise
            except Exception as e:  # noqa: BLE001
                raise self._located(e) from None
        for w in caught or []:
            where = f" (linia {w.lineno})" if w.filename == self.filename else ""
            self._print(f"⚠ {w.category.__name__}{where}: {w.message}")
        self.ms = round((time.monotonic() - t0) * 1000)
        if not isinstance(res, dict) and len(m["outputs"]) == 1:
            res = {m["outputs"][0]["id"]: res}
        if not isinstance(res, dict):
            raise CodeError(
                "run() musi zwrócić słownik {wyjście: wartość} "
                f"(wyjścia: {', '.join(o['id'] for o in m['outputs'])})"
            )
        declared = {o["id"]: o for o in m["outputs"]}
        unknown = [k for k in res if k not in declared]
        if unknown:
            raise CodeError(
                f"Nieznane wyjście „{unknown[0]}” (zadeklarowane: {', '.join(declared)})"
            )
        out: dict[str, Any] = {}
        for oid, port in declared.items():
            if oid not in res or res[oid] is None:
                raise CodeError(f"Brak wyjścia „{port['label']}” ({oid}) w wyniku run()")
            out[oid] = self._convert(ctx, port, res[oid], inputs, oid)
        if self.test and callable(ns.get("test")):
            self._user_test(ns["test"], res, ins, params)
        return out

    def _user_test(self, fn: Any, res: dict, ins: Ns, params: Ns) -> None:
        try:
            fn(res, ins, params)
            self.checks.append({"id": "user", "label": "test()", "level": "ok"})
        except AssertionError as e:
            ce = self._located(e)
            self.checks.append(
                {
                    "id": "user",
                    "label": "test()",
                    "level": "fail",
                    "message": str(e) or "Asercja nie przeszła",
                    "line": ce.line,
                }
            )
        except Exception as e:  # noqa: BLE001
            ce = self._located(e)
            self.checks.append(
                {
                    "id": "user",
                    "label": "test()",
                    "level": "fail",
                    "message": ce.message,
                    "line": ce.line,
                }
            )

    # result conversion -----------------------------------------------------------
    def _convert(self, ctx: EvalContext, port: dict, value: Any, inputs: dict, oid: str) -> Any:
        kind = port["kind"]
        socket = "out" if oid == self.manifest["outputs"][0]["id"] else oid
        label = port["label"]
        if isinstance(value, Volume):
            value = value._v
        if isinstance(value, Mesh):
            value = value._m
        if isinstance(value, VolumeValue):
            if value.kind != kind:
                raise CodeError(f"Wyjście „{label}”: to {value.kind}, a zadeklarowano {kind}")
            return value
        if isinstance(value, MeshValue):
            if kind != "mesh":
                raise CodeError(f"Wyjście „{label}”: to mesh, a zadeklarowano {kind}")
            return value
        if kind in VOLUME_KINDS:
            return self._volume(ctx, port, value, inputs, socket)
        if kind == "mesh":
            return self._mesh(ctx, port, value, inputs, socket)
        if kind == "liczba":
            scalar = isinstance(value, (int, float, np.number)) or (
                isinstance(value, np.ndarray) and value.size == 1
            )
            if not scalar:
                raise CodeError(f"Wyjście „{label}”: oczekiwano liczby, jest {_tname(value)}")
            f = float(np.asarray(value).item())
            if self.test:
                self.stats[oid] = {"value": f}
                if not math.isfinite(f):
                    self._warn(oid, label, "fail", "Wynik nie jest skończoną liczbą (NaN/Inf)")
            return f
        if kind == "tabela":
            return self._table(port, value, oid)
        if kind == "punkty":
            return self._points(port, value)
        raise CodeError(f"Nieobsługiwany rodzaj wyjścia: {kind}")

    def _warn(self, oid: str, label: str, level: str, message: str) -> None:
        self.checks.append({"id": oid, "label": label, "level": level, "message": message})

    def _volume(
        self, ctx: EvalContext, port: dict, value: Any, inputs: dict, socket: str
    ) -> VolumeValue:
        from ..nodes.filtry import window_of
        from ..nodes.segmentacja import PALETTE

        kind, label, oid = port["kind"], port["label"], port["id"]
        opts = value.opts if isinstance(value, Out) else {}
        data = value.data if isinstance(value, Out) else value
        if isinstance(value, Out) and value.kind != "volume":
            raise CodeError(f"Wyjście „{label}”: to {value.kind}, a zadeklarowano {kind}")
        if not isinstance(data, np.ndarray):
            raise CodeError(f"Wyjście „{label}”: oczekiwano tablicy numpy, jest {_tname(data)}")
        if data.ndim != 3:
            raise CodeError(f"Wyjście „{label}”: tablica musi być 3D [k, j, i], ma {data.ndim}D")
        vols = [v for vs in inputs.values() for v in vs or [] if isinstance(v, VolumeValue)]
        ref: VolumeValue | None = None
        like = opts.get("like")
        if isinstance(like, Volume):
            ref = like._v
        g: Geometry | None = opts.get("grid")
        if g is None:
            if ref is None:
                ref = next((v for v in vols if v.geometry.shape_kji == data.shape), None)
            if ref is None:
                raise CodeError(
                    f"Wyjście „{label}”: kształt {tuple(data.shape)} nie pasuje do żadnego "
                    "wejścia — podaj siatkę: ctx.volume(arr, grid=ctx.grid(...))"
                )
            g = ref.geometry
        elif ref is None:
            ref = vols[0] if vols else None
        if g.shape_kji != data.shape:
            raise CodeError(
                f"Wyjście „{label}”: kształt {tuple(data.shape)} ≠ siatka {g.shape_kji}"
            )
        bg = "" if ref is None else (ref.ref if ref.kind == "wolumen" else ref.info.get("ref", ""))
        name = opts.get("name") or (
            f"{ref.info.get('name', 'Wolumen')} · {self.manifest['label']}" if ref else label
        )
        st: dict[str, Any] = {"shape": list(data.shape), "dtype": str(data.dtype)}
        if kind == "segment":
            mask = data if data.dtype == bool else data != 0
            arr = np.ascontiguousarray(mask).view(np.uint8)
            info = {"name": name, "ref": bg, "color": opts.get("color") or PALETTE[0]}
        elif kind == "segmentacja":
            if data.dtype.kind not in "uib":
                raise CodeError(f"Wyjście „{label}”: etykiety muszą być liczbami całkowitymi")
            lo, hi = int(data.min()), int(data.max())
            if lo < 0 or hi > 255:
                raise CodeError(f"Wyjście „{label}”: etykiety muszą mieścić się w 0..255")
            arr = data.astype(np.uint8, copy=False)
            info = {"name": name, "ref": bg, "labels": _labels(arr, opts.get("labels"), ref)}
        else:
            arr = _display_dtype(data)
            same = ref is not None and ref.kind == "wolumen" and arr.dtype == ref.array().dtype
            if same and ref is not None:
                keep = ("modality", "window", "sourceVid")
                info = {k: v for k, v in ref.info.items() if k in keep}
            else:
                info = {"window": window_of(arr), "modality": ""}
            info["name"] = name
            if opts.get("window"):
                c, w = opts["window"]
                info["window"] = {"center": float(c), "width": max(float(w), 1e-6)}
            if self.test:
                self._volume_checks(oid, label, data, arr, st)
        out = ctx.volume_result(arr, g, info, socket=socket, kind=kind)
        if self.test:
            if kind != "wolumen":
                nvox = int(out.info.get("voxels", 0))
                st.update(voxels=nvox, ml=out.info.get("ml", 0))
                if nvox == 0:
                    self._warn(oid, label, "warn", "Pusty wynik — żaden woksel nie jest zaznaczony")
                elif nvox == arr.size:
                    self._warn(oid, label, "warn", "Zaznaczony cały wolumen — sprawdź warunek")
            self.stats[oid] = st
        return out

    def _volume_checks(
        self, oid: str, label: str, data: np.ndarray, arr: np.ndarray, st: dict
    ) -> None:
        if arr.dtype != data.dtype:
            st["converted"] = str(arr.dtype)
            self._warn(oid, label, "info", f"Typ {data.dtype} zapisany jako {arr.dtype}")
        if arr.dtype.kind == "f":
            bad = int(arr.size - np.count_nonzero(np.isfinite(arr)))
            if bad:
                self._warn(oid, label, "fail", f"{bad} wokseli to NaN/Inf")
                st["nan"] = bad
            fin = arr[np.isfinite(arr)] if bad else arr
            lo, hi, mean = (
                (float(fin.min()), float(fin.max()), float(fin.mean())) if fin.size else (0, 0, 0)
            )
        else:
            lo, hi, mean = float(arr.min()), float(arr.max()), float(arr.mean())
        st.update(min=lo, max=hi, mean=round(mean, 4))
        if lo == hi:
            self._warn(oid, label, "warn", f"Wolumen stały (wszędzie {lo:g})")

    def _mesh(
        self, ctx: EvalContext, port: dict, value: Any, inputs: dict, socket: str
    ) -> MeshValue:
        from ..meshes import ops
        from ..nodes.segmentacja import PALETTE

        label = port["label"]
        opts = value.opts if isinstance(value, Out) else {}
        data = value.data if isinstance(value, Out) else value
        if not (isinstance(data, (tuple, list)) and len(data) == 2):
            raise CodeError(
                f"Wyjście „{label}”: mesh to (wierzchołki [N,3] mm, trójkąty [M,3]), "
                f"jest {_tname(data)}"
            )
        v = np.asarray(data[0], dtype=np.float32)
        f = np.asarray(data[1])
        if v.ndim != 2 or v.shape[1] != 3 or f.ndim != 2 or f.shape[1] != 3:
            raise CodeError(f"Wyjście „{label}”: wierzchołki [N,3] i trójkąty [M,3]")
        if f.size and (f.min() < 0 or f.max() >= len(v)):
            raise CodeError(f"Wyjście „{label}”: indeks trójkąta poza listą wierzchołków")
        if not np.all(np.isfinite(v)):
            raise CodeError(f"Wyjście „{label}”: wierzchołki zawierają NaN/Inf")
        f = ops.orient_outwards(v, f.astype(np.int64))
        bg = ""
        for vs in inputs.values():
            for x in vs or []:
                if isinstance(x, VolumeValue) and not bg:
                    bg = x.ref if x.kind == "wolumen" else x.info.get("ref", "")
                if isinstance(x, MeshValue) and not bg:
                    bg = x.info.get("ref", "")
        info = {
            "name": opts.get("name") or label,
            "color": opts.get("color") or PALETTE[5],
            "ref": bg,
        }
        out = ctx.mesh_result(v, f, info, socket=socket)
        if self.test:
            self.stats[port["id"]] = {
                "verts": int(len(v)),
                "faces": int(len(f)),
                "closed": out.info.get("closed"),
                "ml": out.info.get("ml"),
            }
            if not len(f):
                self._warn(port["id"], label, "warn", "Mesh bez trójkątów")
        return out

    def _table(self, port: dict, value: Any, oid: str) -> DataValue:
        from ..nodes.pomiary import table

        label = port["label"]
        opts = value.opts if isinstance(value, Out) else {}
        rows = value.data if isinstance(value, Out) else value
        if isinstance(rows, dict) and "rows" in rows:
            opts = {"columns": rows.get("columns"), "title": rows.get("title", ""), **opts}
            rows = rows["rows"]
        if isinstance(rows, dict):  # {name: value} → two columns
            rows = [{"name": k, "value": v} for k, v in rows.items()]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise CodeError(f"Wyjście „{label}”: tabela to lista słowników, jest {_tname(rows)}")
        clean = [{str(k): _py(v) for k, v in r.items()} for r in rows[:100_000]]
        cols: list[tuple[str, str, str]] = []
        for c in opts.get("columns") or []:
            if isinstance(c, dict):
                c = (c["key"], c.get("label", c["key"]), c.get("unit", ""))
            if isinstance(c, (list, tuple)):
                key = str(c[0])
                cols.append(
                    (key, str(c[1]) if len(c) > 1 else key, str(c[2]) if len(c) > 2 else "")
                )
            else:
                cols.append((str(c), str(c), ""))
        if not cols:
            keys: dict[str, None] = {}
            for r in clean:
                keys.update(dict.fromkeys(r))
            cols = [(k, k, "") for k in keys]
        chart = None
        if opts.get("chart") == "bars" and len(cols) >= 2:
            chart = {"type": "bars", "label": cols[0][0], "value": cols[1][0]}
        elif opts.get("chart") in ("histogram", "line") and len(cols) >= 2:
            chart = {"type": opts["chart"], "x": cols[0][0], "y": cols[1][0]}
        if self.test:
            self.stats[oid] = {"rows": len(clean), "columns": len(cols)}
        title = str(opts.get("title") or self.manifest["label"])
        return table(cols, clean, chart=chart, title=title)

    def _points(self, port: dict, value: Any) -> DataValue:
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if not isinstance(value, list):
            raise CodeError(f"Wyjście „{port['label']}”: punkty to lista [x, y, z] w mm")
        items = []
        for n, pt in enumerate(value, 1):
            if isinstance(pt, dict) and "p" in pt:
                items.append(pt)
                continue
            try:
                xyz = [round(float(c), 3) for c in pt[:3]]
            except (TypeError, ValueError, IndexError):
                raise CodeError(f"Wyjście „{port['label']}”: punkt {n} to nie [x, y, z]") from None
            if len(xyz) != 3:
                raise CodeError(f"Wyjście „{port['label']}”: punkt {n} to nie [x, y, z]")
            items.append(
                {
                    "id": f"p{n}",
                    "type": "point",
                    "name": f"Punkt {n}",
                    "p": [xyz],
                    "value": None,
                    "unit": "",
                }
            )
        return DataValue("punkty", {"items": items})


def wrap_input(v: Any) -> Any:
    if isinstance(v, VolumeValue):
        return Volume(v)
    if isinstance(v, MeshValue):
        return Mesh(v)
    if isinstance(v, DataValue):
        if v.kind == "punkty":
            return list((v.value or {}).get("items", []))
        return v.value
    return v


def _display_dtype(a: np.ndarray) -> np.ndarray:
    if a.dtype.name in _DTYPES:
        return a
    if a.dtype == bool:
        return np.ascontiguousarray(a).view(np.uint8)
    if a.dtype.kind == "f" or a.dtype.kind == "c":
        return np.real(a).astype(np.float32) if a.dtype.kind == "c" else a.astype(np.float32)
    if a.dtype == np.int8:
        return a.astype(np.int16)
    info = np.iinfo(np.int32)
    return np.clip(a, info.min, info.max).astype(np.int32)


def _labels(arr: np.ndarray, names: list[Any] | None, ref: VolumeValue | None) -> list[dict]:
    from ..nodes.segmentacja import PALETTE

    if names:
        out = []
        for n, x in enumerate(names, 1):
            d = x if isinstance(x, dict) else {"name": str(x)}
            out.append(
                {
                    "id": int(d.get("id", n)),
                    "name": str(d.get("name", f"Etykieta {n}")),
                    "color": str(d.get("color", PALETTE[(n - 1) % len(PALETTE)])),
                }
            )
        return out
    if ref is not None and ref.kind == "segmentacja" and ref.info.get("labels"):
        return list(ref.info["labels"])
    present = np.zeros(256, bool)
    flat = arr.reshape(-1)
    for p in range(0, flat.size, 1 << 24):
        present |= np.bincount(flat[p : p + (1 << 24)], minlength=256) > 0
    return [
        {"id": int(i), "name": f"Etykieta {i}", "color": PALETTE[(i - 1) % len(PALETTE)]}
        for i in np.flatnonzero(present)
        if i
    ]


def _py(v: Any) -> Any:
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _tname(v: Any) -> str:
    if isinstance(v, np.ndarray):
        return f"ndarray {v.shape} {v.dtype}"
    if isinstance(v, Out):
        return v.kind
    return type(v).__name__
