# PyInstaller spec for the praTRD sidecar — run from the project root:
#   uv run pyinstaller app/sidecar/sidecar.spec --noconfirm --distpath app/sidecar/dist
#
# --onedir layout (dist/sidecar/{sidecar[.exe], _internal/}): starts much faster than
# onefile, which would unpack ~300 MB of numpy/SimpleITK/scipy to a temp dir on every launch.
#
# The processing stack is imported lazily at runtime, so static analysis misses most of it:
# packages are collected whole. pylibjpeg discovers its decoder plugins through
# importlib.metadata entry points — their dist-info must be copied or JPEG DICOMs fail.

import importlib.metadata
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# stdlib modules that are platform-specific, GUI or test-only (they fail or only bloat)
_SKIP_STDLIB = {
    "antigravity", "this", "idlelib", "turtle", "turtledemo", "tkinter", "_tkinter", "test",
    "lib2to3", "ensurepip", "venv", "msvcrt", "winreg", "winsound", "_winapi", "_overlapped",
    "nt", "_msi", "msilib", "_wmi", "pydoc_data",
}

root = Path(SPECPATH).parents[1]

datas, binaries, hiddenimports = [], [], []
for pkg in (
    "pratrd", "pydicom", "pylibjpeg", "libjpeg", "openjpeg", "SimpleITK",
    "zarr", "numcodecs", "highdicom", "nibabel", "PIL", "websockets", "fast_simplification",
    "pip",  # Kreator: `sidecar --pip install …` for user-node packages
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
for dist in ("pylibjpeg", "pylibjpeg-libjpeg", "pylibjpeg-openjpeg", "pydicom", "zarr", "numcodecs"):
    datas += copy_metadata(dist)
hiddenimports += collect_submodules("uvicorn") + collect_submodules("skimage")
# User nodes may import anything: the whole standard library (not just what the app uses)
# and the metadata of every bundled distribution (so pip sees them as installed).
hiddenimports += [m for m in sys.stdlib_module_names if m not in _SKIP_STDLIB]
for _dist in importlib.metadata.distributions():
    try:
        datas += copy_metadata(_dist.metadata["Name"])
    except Exception:  # noqa: BLE001 — a dist without usable metadata is just not listed
        pass

a = Analysis(
    [str(root / "app" / "sidecar" / "main.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sidecar",
    console=False,
    upx=False,
    strip=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="sidecar", upx=False, strip=False)
