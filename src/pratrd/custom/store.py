"""User nodes on disk — global, like notes and boards:
custom_nodes/<slug>/node.json (manifest) + custom_nodes/<slug>/code.py.

Each one is registered as node type "wlasne/<slug>"; its code is compiled lazily, so
startup only reads the small manifests.
"""

import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..graph.types import REGISTRY, register, unregister
from ..jsonio import read_json, write_json, write_text
from . import manifest as mf
from .runtime import Runtime

FILE_FORMAT = "pratrd-node"


class CustomNodeError(Exception):
    def __init__(self, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build(m: dict[str, Any], code: str, test: bool = False, type_id: str | None = None):  # noqa: ANN201
    rt = Runtime(m["slug"], m, code, test=test)
    return mf.node_type(m, code, rt, type_id), rt


class CustomNodeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self.broken: dict[str, str] = {}  # slug → why it is not registered

    def _dir(self, slug: str) -> Path:
        if not mf.SLUG.match(slug):
            raise CustomNodeError("Nieprawidłowy identyfikator node'a")
        return self.root / slug

    # ── registry ──────────────────────────────────────────────────────────────
    def load_all(self) -> None:
        if not self.root.is_dir():
            return
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "node.json").is_file():
                self._register(d.name)

    def _register(self, slug: str) -> None:
        d = self._dir(slug)
        unregister(mf.PREFIX + slug)
        try:
            m = mf.clean({**read_json(d / "node.json", {}), "slug": slug})
            code = (d / "code.py").read_text(encoding="utf-8") if (d / "code.py").is_file() else ""
        except (mf.ManifestError, OSError) as e:
            self.broken[slug] = str(e)
            return
        self.broken.pop(slug, None)
        register(build(m, code)[0])

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def list(self) -> list[dict[str, Any]]:
        out = []
        if not self.root.is_dir():
            return out
        for d in sorted(self.root.iterdir()):
            if not (d.is_dir() and (d / "node.json").is_file()):
                continue
            m = read_json(d / "node.json", {})
            out.append(
                {
                    "slug": d.name,
                    "label": str(m.get("label") or d.name),
                    "domain": m.get("domain", "wlasne"),
                    "updatedAt": m.get("updatedAt", ""),
                    "error": self.broken.get(d.name, ""),
                }
            )
        return out

    def get(self, slug: str) -> dict[str, Any]:
        d = self._dir(slug)
        if not (d / "node.json").is_file():
            raise CustomNodeError("Node nie istnieje", 404)
        m = read_json(d / "node.json", {})
        code = (d / "code.py").read_text(encoding="utf-8") if (d / "code.py").is_file() else ""
        return {"manifest": {**m, "slug": slug}, "code": code}

    def save(
        self, raw: dict[str, Any], code: str, previous: str | None, overwrite: bool = False
    ) -> dict[str, Any]:
        """previous = slug the editor opened (None for a new node). A name already used by
        another node is a conflict unless `overwrite` — never a silent replace."""
        m = mf.clean(raw)
        slug = m["slug"]
        with self._lock:
            d = self._dir(slug)
            if slug != previous and d.exists() and not overwrite:
                raise CustomNodeError(f"Node „{slug}” już istnieje", 409)
            created = read_json(d / "node.json", {}).get("createdAt") if d.exists() else None
            if previous and previous != slug:
                old = self._dir(previous)
                if old.is_dir():
                    created = read_json(old / "node.json", {}).get("createdAt", created)
            write_text(d / "code.py", code)
            write_json(d / "node.json", {**m, "createdAt": created or _now(), "updatedAt": _now()})
            if previous and previous != slug:
                shutil.rmtree(self._dir(previous), ignore_errors=True)
                unregister(mf.PREFIX + previous)
                self.broken.pop(previous, None)
            self._register(slug)
        return self.get(slug)

    def delete(self, slug: str) -> None:
        with self._lock:
            shutil.rmtree(self._dir(slug), ignore_errors=True)
            unregister(mf.PREFIX + slug)
            self.broken.pop(slug, None)

    # ── one-file exchange (.pratrdnode) ─────────────────────────────────────────
    def export(self, slug: str, path: Path) -> None:
        node = self.get(slug)
        m = {k: v for k, v in node["manifest"].items() if k not in ("createdAt", "updatedAt")}
        write_json(path, {"format": FILE_FORMAT, "version": 1, "manifest": m, "code": node["code"]})

    def read_file(self, path: Path) -> dict[str, Any]:
        d = read_json(path, None)
        if not isinstance(d, dict) or d.get("format") != FILE_FORMAT:
            raise CustomNodeError("To nie jest plik node'a praTRD (.pratrdnode)")
        m = mf.clean(d.get("manifest"))
        return {"manifest": m, "code": str(d.get("code") or ""), "exists": self.exists(m["slug"])}

    def exists(self, slug: str) -> bool:
        return (self._dir(slug) / "node.json").is_file()

    def is_registered(self, slug: str) -> bool:
        return (mf.PREFIX + slug) in REGISTRY
