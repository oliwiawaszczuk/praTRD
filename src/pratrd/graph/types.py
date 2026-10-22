"""Node-type definitions — the single source of truth for ports, parameters and docs.

The frontend never hard-codes node types: it renders palette entries, sockets and
parameter widgets from `GET /node-types` (the schema produced here).
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PortKind = Literal["wolumen", "segmentacja", "segment", "punkty", "tabela", "liczba"]
Domain = Literal["wolumen", "segmentacja", "pomiary"]
Stage = Literal["dane", "przetwarzanie", "wynik"]
# "points": [[x,y,z] mm, …] (e.g. seeds clicked in a view);
# "strokes": [{"p": [[x,y,z], …], "r": mm, "mode": "add"|"erase"}, …] (brush edits)
# "markups": [{"id", "type": point|line|angle|roi, "name", "p": [[x,y,z] mm, …]}, …]
ParamType = Literal["number", "int", "select", "bool", "volume", "points", "strokes", "markups"]
Cost = Literal["light", "heavy"]

DOMAIN_LABELS: dict[str, str] = {
    "wolumen": "Wolumen",
    "segmentacja": "Segmentacja",
    "pomiary": "Pomiary i statystyki",
}


@dataclass(frozen=True)
class Port:
    id: str  # stable — saved graphs reference it
    label: str
    kind: PortKind
    multi: bool = False  # input accepting several edges
    optional: bool = False  # the node runs without this input


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    type: ParamType
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    options: tuple[tuple[str, str], ...] = ()  # (value, label) for "select"
    help: str = ""
    show_if: tuple[str, Any] | None = None  # (param key, value) → only then relevant


@dataclass(frozen=True)
class NodeType:
    id: str  # "domena/nazwa"
    label: str
    domain: Domain
    stage: Stage
    description: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    params: tuple[Param, ...]
    run: Callable[..., dict[str, Any]] = field(compare=False, repr=False)
    cost: Cost = "light"
    # custom editor in the UI instead of generic param widgets (e.g. "cropbox": 3-D box modal)
    widget: str = ""
    version: int = 1  # bump when the algorithm changes → old cached results are not reused

    def schema(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("run")
        for p in d["params"]:
            p["options"] = [{"value": v, "label": lbl} for v, lbl in p["options"]]
            p["showIf"] = p.pop("show_if")
        return d

    def defaults(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.params}

    def clean_params(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        """Defaults + coercion + clamping: a saved graph with stale/garbage values still runs,
        and equal settings always hash to the same cache key."""
        raw = raw or {}
        out: dict[str, Any] = {}
        for p in self.params:
            v = raw.get(p.key, p.default)
            try:
                if p.type == "number":
                    v = float(v)
                elif p.type == "int":
                    v = int(round(float(v)))
                elif p.type == "bool":
                    v = bool(v)
                elif p.type == "select":
                    v = str(v) if str(v) in {o for o, _ in p.options} else p.default
                elif p.type == "points":
                    v = [[round(float(c), 3) for c in pt[:3]] for pt in (v or []) if len(pt) >= 3]
                elif p.type == "strokes":
                    v = [
                        {
                            "p": [
                                [round(float(c), 3) for c in pt[:3]]
                                for pt in st.get("p", [])
                                if len(pt) >= 3
                            ],
                            "r": max(0.1, float(st.get("r", 2.0))),
                            "mode": "erase" if st.get("mode") == "erase" else "add",
                        }
                        for st in (v or [])
                        if isinstance(st, dict)
                    ]
                elif p.type == "markups":
                    v = [m for m in (_clean_markup(m) for m in (v or [])) if m]
                else:
                    v = str(v or "")
            except (TypeError, ValueError):
                v = p.default
            if p.type in ("number", "int"):
                if p.min is not None:
                    v = max(p.min, v)
                if p.max is not None:
                    v = min(p.max, v)
            out[p.key] = v
        return out


REGISTRY: dict[str, NodeType] = {}


def register(nt: NodeType) -> NodeType:
    if nt.id in REGISTRY:
        raise ValueError(f"duplicate node type {nt.id}")
    REGISTRY[nt.id] = nt
    return nt


def schema() -> dict[str, Any]:
    return {
        "domains": DOMAIN_LABELS,
        "types": [nt.schema() for nt in REGISTRY.values()],
    }


MARKUP_POINTS = {"point": 1, "line": 2, "angle": 3, "roi": 2}


def _clean_markup(m: Any) -> dict[str, Any] | None:
    if not isinstance(m, dict) or m.get("type") not in MARKUP_POINTS:
        return None
    pts = [[round(float(c), 3) for c in pt[:3]] for pt in m.get("p", []) if len(pt) >= 3]
    if len(pts) != MARKUP_POINTS[m["type"]]:
        return None  # unfinished (e.g. an angle with two points) is not part of the graph
    return {
        "id": str(m.get("id", ""))[:16],
        "type": m["type"],
        "name": str(m.get("name", ""))[:60],
        "p": pts,
    }
