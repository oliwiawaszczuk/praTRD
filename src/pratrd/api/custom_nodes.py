"""Node creator (zakładka Kreator): user nodes CRUD, instant code check, test runs,
.pratrdnode import/export. Every change re-registers the type and tells the UI
("node-types" event) to reload the palette."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request

from ..custom import packages, tester
from ..custom.manifest import ManifestError
from ..custom.runtime import Runtime
from ..custom.store import CustomNodeError, CustomNodeStore
from ..jobs import Job
from .graphs import evaluator_for

router = APIRouter(prefix="/custom-nodes")


def _store(request: Request) -> CustomNodeStore:
    return request.app.state.custom_nodes


def _changed(request: Request) -> None:
    request.app.state.hub.publish({"type": "node-types"})


def _manifest_error(e: ManifestError) -> CustomNodeError:
    return CustomNodeError(str(e))


@router.get("")
def list_nodes(request: Request) -> dict:
    return {"nodes": _store(request).list()}


@router.get("/libraries")
def libraries(request: Request) -> dict:
    return packages.listing(request.app.state.config.root)


@router.post("/libraries/install")
def install_library(request: Request, body: dict = Body(...)) -> dict:
    st = request.app.state
    spec = str(body.get("spec") or "")

    def run(job: Job) -> dict[str, Any]:
        return packages.install(job, st.config.root, spec)

    job = st.jobs.submit("pip", f"Instalacja: {spec.strip()[:40]}", "", run, lane="heavy")
    return {"jobId": job.id}


@router.delete("/libraries/{name}")
def uninstall_library(request: Request, name: str) -> dict:
    try:
        packages.uninstall(request.app.state.config.root, name)
    except packages.PackageError as e:
        raise CustomNodeError(str(e), 404) from None
    return {"ok": True}


@router.get("/{slug}")
def get_node(request: Request, slug: str) -> dict:
    return _store(request).get(slug)


@router.put("/{slug}")
def save_node(request: Request, slug: str, body: dict = Body(...)) -> dict:
    """`slug` = the node being edited ("_" for a new one); the manifest's slug may differ
    (rename)."""
    try:
        out = _store(request).save(
            body.get("manifest") or {},
            str(body.get("code") or ""),
            None if slug == "_" else slug,
            overwrite=bool(body.get("overwrite")),
        )
    except ManifestError as e:
        raise _manifest_error(e) from None
    _changed(request)
    return out


@router.delete("/{slug}")
def delete_node(request: Request, slug: str) -> dict:
    _store(request).delete(slug)
    _changed(request)
    return {"ok": True}


@router.post("/check")
def check_code(body: dict = Body(...)) -> dict:
    err = Runtime("check", {}, str(body.get("code") or "")).check_code()
    if err is None:
        return {"ok": True, "message": "", "line": None}
    return {"ok": False, "message": err.message, "line": err.line}


@router.post("/validate")
def validate(body: dict = Body(...)) -> dict:
    from ..custom.manifest import clean

    try:
        clean(body.get("manifest"))
    except ManifestError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": ""}


@router.post("/test")
def test_node(request: Request, body: dict = Body(...)) -> dict:
    st = request.app.state
    wid = str(body.get("wid") or "")
    ws_dir = st.workspaces.existing_dir(wid)
    try:
        from ..custom.manifest import clean

        clean(body.get("manifest"))
    except ManifestError as e:
        raise _manifest_error(e) from None
    ev = evaluator_for(st, wid, ws_dir)

    def run(job: Job) -> dict[str, Any]:
        return tester.run_test(job, ev, body)

    job = st.jobs.submit("node-test", "Test node'a", wid, run, lane="graph")
    return {"jobId": job.id}


@router.post("/{slug}/export")
def export_node(request: Request, slug: str, body: dict = Body(...)) -> dict:
    path = Path(str(body.get("path") or "")).expanduser()
    if not path.is_absolute() or path.suffix != ".pratrdnode":
        raise CustomNodeError("Nieprawidłowa ścieżka pliku")
    _store(request).export(slug, path)
    return {"ok": True}


@router.post("/read-file")
def read_file(request: Request, body: dict = Body(...)) -> dict:
    """Preview of an import (manifest + code + whether the name is taken) — the editor then
    saves it through PUT, so a name conflict is always a question, never an overwrite."""
    path = Path(str(body.get("path") or "")).expanduser()
    if not path.is_file():
        raise CustomNodeError("Plik nie istnieje", 404)
    try:
        return _store(request).read_file(path)
    except ManifestError as e:
        raise _manifest_error(e) from None
