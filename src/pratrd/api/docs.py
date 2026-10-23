"""User documentation (zakładka Dokumentacja) — app_docs.json in the data root:
tabs (guide per app tab), nodes (overrides of node-type descriptions, shared with the (i)
on node cards) and pages (the user's own pages, in display order)."""

import threading

from fastapi import APIRouter, Body, Request

from ..jsonio import read_json, write_json

router = APIRouter(prefix="/app_docs")
_lock = threading.Lock()


def _clean(d: object) -> dict:
    d = d if isinstance(d, dict) else {}
    tabs = d.get("tabs") if isinstance(d.get("tabs"), dict) else {}
    nodes = d.get("nodes") if isinstance(d.get("nodes"), dict) else {}
    pages = d.get("pages") if isinstance(d.get("pages"), list) else []
    return {
        "tabs": {str(k): str(v) for k, v in tabs.items()},
        "nodes": {str(k): str(v) for k, v in nodes.items()},
        "pages": [
            {
                "id": str(p.get("id", "")),
                "title": str(p.get("title", "")),
                "body": str(p.get("body", "")),
            }
            for p in pages
            if isinstance(p, dict) and p.get("id")
        ],
    }


@router.get("")
def get_docs(request: Request) -> dict:
    return _clean(read_json(request.app.state.config.app_docs_file, {}))


@router.put("")
def put_docs(request: Request, body: dict = Body(...)) -> dict:
    with _lock:
        write_json(request.app.state.config.app_docs_file, _clean(body))
    return {"ok": True}
