"""Manifest of a user node (zakładka Kreator): name, category, ports, parameters.

Everything coming from the editor is validated here — a broken manifest never reaches the
registry, and errors are messages the creator can show next to the offending field.
"""

import hashlib
import json
import keyword
import re
from typing import Any

from ..graph.types import DOMAIN_LABELS, NodeType, Param, Port

PORT_KINDS = ("wolumen", "segment", "segmentacja", "mesh", "tabela", "liczba", "punkty")
PARAM_TYPES = ("number", "int", "bool", "select")
SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,23}$")
MAX_PORTS = 8
MAX_PARAMS = 16
PREFIX = "wlasne/"


class ManifestError(ValueError):
    pass


def _ident(v: Any, what: str) -> str:
    s = str(v or "").strip()
    if not IDENT.match(s) or keyword.iskeyword(s):
        raise ManifestError(
            f"{what} „{s}”: tylko małe litery, cyfry i _, nie może zaczynać się cyfrą"
        )
    return s


def _text(v: Any, what: str, max_len: int, required: bool = True) -> str:
    s = str(v or "").strip()
    if required and not s:
        raise ManifestError(f"Brak: {what}")
    return s[:max_len]


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ManifestError(f"Nieprawidłowa liczba: {v}") from None
    return f


def _ports(raw: Any, side: str) -> list[dict[str, Any]]:
    what = "Wejście" if side == "in" else "Wyjście"
    items = raw if isinstance(raw, list) else []
    if len(items) > MAX_PORTS:
        raise ManifestError(f"Za dużo gniazd ({side}): maks. {MAX_PORTS}")
    out, seen = [], set()
    for p in items:
        if not isinstance(p, dict):
            continue
        pid = _ident(p.get("id"), what)
        if pid in seen:
            raise ManifestError(f"{what} „{pid}” występuje dwa razy")
        seen.add(pid)
        kind = p.get("kind")
        if kind not in PORT_KINDS:
            raise ManifestError(f"{what} „{pid}”: nieznany rodzaj {kind}")
        d = {"id": pid, "label": _text(p.get("label") or pid, "etykieta", 40), "kind": kind}
        if side == "in":
            d["multi"] = bool(p.get("multi"))
            d["optional"] = bool(p.get("optional"))
        out.append(d)
    return out


def _param(p: dict[str, Any]) -> dict[str, Any]:
    key = _ident(p.get("key"), "Parametr")
    t = p.get("type")
    if t not in PARAM_TYPES:
        raise ManifestError(f"Parametr „{key}”: nieznany typ {t}")
    d: dict[str, Any] = {
        "key": key,
        "label": _text(p.get("label") or key, "etykieta", 40),
        "type": t,
        "help": _text(p.get("help"), "opis", 300, required=False),
    }
    if t in ("number", "int"):
        lo, hi, step = _num(p.get("min")), _num(p.get("max")), _num(p.get("step"))
        if lo is not None and hi is not None and lo >= hi:
            raise ManifestError(f"Parametr „{key}”: min musi być mniejsze od max")
        default = _num(p.get("default"))
        default = 0.0 if default is None else default
        if lo is not None:
            default = max(lo, default)
        if hi is not None:
            default = min(hi, default)
        if t == "int":
            default = round(default)
        d.update(
            min=lo,
            max=hi,
            step=step if step and step > 0 else None,
            unit=_text(p.get("unit"), "jednostka", 12, required=False),
            default=default,
        )
    elif t == "bool":
        d["default"] = bool(p.get("default"))
    else:
        opts = []
        for o in p.get("options") or []:
            v = _text(o.get("value") if isinstance(o, dict) else o, "wartość opcji", 40)
            lbl = o.get("label") if isinstance(o, dict) else None
            if v not in {x["value"] for x in opts}:
                opts.append({"value": v, "label": _text(lbl or v, "etykieta", 40)})
        if not opts:
            raise ManifestError(f"Parametr „{key}”: lista wyboru potrzebuje opcji")
        dv = str(p.get("default") or "")
        d.update(options=opts, default=dv if dv in {o["value"] for o in opts} else opts[0]["value"])
    return d


def clean(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError("Nieprawidłowa definicja node'a")
    slug = str(raw.get("slug") or "")
    if not SLUG.match(slug):
        raise ManifestError("Identyfikator: małe litery, cyfry i _, zaczyna się literą")
    domain = raw.get("domain") or "wlasne"
    if domain not in DOMAIN_LABELS:
        raise ManifestError(f"Nieznana kategoria: {domain}")
    outputs = _ports(raw.get("outputs"), "out")
    if not outputs:
        raise ManifestError("Node musi mieć co najmniej jedno wyjście")
    params_raw = [p for p in raw.get("params") or [] if isinstance(p, dict)]
    if len(params_raw) > MAX_PARAMS:
        raise ManifestError(f"Za dużo parametrów: maks. {MAX_PARAMS}")
    params = [_param(p) for p in params_raw]
    keys = [p["key"] for p in params]
    if len(set(keys)) != len(keys):
        raise ManifestError("Dwa parametry mają ten sam klucz")
    return {
        "slug": slug,
        "label": _text(raw.get("label"), "nazwa", 60),
        "domain": domain,
        "description": _text(raw.get("description"), "opis", 4000, required=False),
        "inputs": _ports(raw.get("inputs"), "in"),
        "outputs": outputs,
        "params": params,
        "cost": "heavy" if raw.get("cost") == "heavy" else "light",
    }


def version_of(m: dict[str, Any], code: str) -> int:
    """Hash of what changes results (code, sockets, parameter types) — labels and texts do
    not, so renaming a port keeps the cache. Fits in a JS-safe integer."""
    sig = {
        "in": [(p["id"], p["kind"], p["multi"], p["optional"]) for p in m["inputs"]],
        "out": [(p["id"], p["kind"]) for p in m["outputs"]],
        "params": [(p["key"], p["type"]) for p in m["params"]],
    }
    h = hashlib.sha256((code + "\0" + json.dumps(sig, sort_keys=True)).encode())
    return int(h.hexdigest()[:12], 16)


def stage_of(m: dict[str, Any]) -> str:
    if not m["inputs"]:
        return "dane"
    if all(p["kind"] in ("tabela", "liczba") for p in m["outputs"]):
        return "wynik"
    return "przetwarzanie"


def node_type(m: dict[str, Any], code: str, run: Any, type_id: str | None = None) -> NodeType:
    return NodeType(
        id=type_id or PREFIX + m["slug"],
        label=m["label"],
        domain=m["domain"],
        stage=stage_of(m),  # type: ignore[arg-type]
        description=m["description"] or "Node własny (Kreator).",
        inputs=tuple(
            Port(p["id"], p["label"], p["kind"], multi=p["multi"], optional=p["optional"])
            for p in m["inputs"]
        ),
        outputs=tuple(Port(p["id"], p["label"], p["kind"]) for p in m["outputs"]),
        params=tuple(
            Param(
                p["key"],
                p["label"],
                p["type"],
                p["default"],
                min=p.get("min"),
                max=p.get("max"),
                step=p.get("step"),
                unit=p.get("unit", ""),
                options=tuple((o["value"], o["label"]) for o in p.get("options", [])),
                help=p.get("help", ""),
            )
            for p in m["params"]
        ),
        run=run,
        cost=m["cost"],
        version=version_of(m, code),
        custom=True,
    )
