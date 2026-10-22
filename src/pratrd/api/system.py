"""Health check (hot path during boot — no heavy imports) and dependency diagnostics."""

import importlib
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import __version__

router = APIRouter()

_STARTED = time.monotonic()

# Packages the processing stack relies on. Diagnostics imports each one, so a frozen
# (PyInstaller) build that silently dropped a module or a plugin fails loudly here — CI
# calls this endpoint on the built binary.
_DEPS = (
    "numpy",
    "pydicom",
    "pylibjpeg",
    "libjpeg",
    "openjpeg",
    "SimpleITK",
    "zarr",
    "numcodecs",
    "PIL",
    "websockets",
    "skimage",
    "scipy",
    "nibabel",
    "highdicom",
)


@router.get("/health")
def health() -> dict:
    uptime = round(time.monotonic() - _STARTED, 1)
    return {"app": "praTRD", "version": __version__, "uptime_s": uptime}


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict:
    deps: dict[str, str | None] = {}
    for name in _DEPS:
        try:
            mod = importlib.import_module(name)
            deps[name] = str(getattr(mod, "__version__", "ok"))
        except Exception as e:  # noqa: BLE001 — report any import failure verbatim
            deps[name] = None
            deps[f"{name}_error"] = f"{type(e).__name__}: {e}"

    decoders: dict[str, bool] = {}
    try:
        from pydicom.pixels import decoders as dec

        for attr in (
            "JPEGLosslessSV1Decoder",
            "JPEGLosslessDecoder",
            "JPEGBaseline8BitDecoder",
            "JPEG2000LosslessDecoder",
            "JPEG2000Decoder",
            "RLELosslessDecoder",
        ):
            decoders[attr] = bool(getattr(dec, attr).is_available)
    except Exception:  # noqa: BLE001
        pass

    ok = (
        all(v is not None for k, v in deps.items() if not k.endswith("_error"))
        and all(decoders.values())
        and bool(decoders)
    )
    return {
        "ok": ok,
        "deps": deps,
        "decoders": decoders,
        "data_root": str(request.app.state.config.root),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
    }


class CsvExport(BaseModel):
    path: str  # absolute, chosen by the user in the native "Save" dialog
    text: str


@router.post("/export/csv")
def export_csv(body: CsvExport) -> dict:
    """The webview has no file-system access: tables are written here. UTF-8 with BOM so
    Excel shows Polish characters and units (mm³) correctly."""
    p = Path(body.path)
    if not p.is_absolute() or p.suffix.lower() != ".csv":
        raise HTTPException(400, "Oczekiwano bezwzględnej ścieżki do pliku .csv")
    if not p.parent.is_dir():
        raise HTTPException(400, "Folder nie istnieje")
    p.write_text(body.text, encoding="utf-8-sig", newline="")
    return {"path": str(p), "bytes": p.stat().st_size}
