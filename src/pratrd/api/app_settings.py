"""Global (not per-workspace) app settings — app_settings.json in the data root."""

import threading

from fastapi import APIRouter, Body, Request

from ..jsonio import read_json, write_json

router = APIRouter(prefix="/app_settings")
_lock = threading.Lock()


@router.get("")
def get_app_settings(request: Request) -> dict:
    data = read_json(request.app.state.config.app_settings_file, {})
    return data if isinstance(data, dict) else {}


@router.put("")
def put_app_settings(request: Request, body: dict = Body(...)) -> dict:
    with _lock:
        write_json(request.app.state.config.app_settings_file, body)
    return {"ok": True}
