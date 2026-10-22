# PyInstaller spec for the praTRD sidecar — run from the project root:
#   uv run pyinstaller app/sidecar/sidecar.spec --noconfirm --distpath app/sidecar/dist
#
# --onedir layout (dist/sidecar/{sidecar[.exe], _internal/}): starts much faster than
# onefile, which would unpack ~300 MB of numpy/SimpleITK/scipy to a temp dir on every launch.
#
# The processing stack is imported lazily at runtime, so static analysis misses most of it:
# packages are collected whole. pylibjpeg discovers its decoder plugins through
# importlib.metadata entry points — their dist-info must be copied or JPEG DICOMs fail.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parents[1]

datas, binaries, hiddenimports = [], [], []
for pkg in (
    "pratrd", "pydicom", "pylibjpeg", "libjpeg", "openjpeg", "SimpleITK",
    "zarr", "numcodecs", "highdicom", "nibabel", "PIL", "websockets",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
for dist in ("pylibjpeg", "pylibjpeg-libjpeg", "pylibjpeg-openjpeg", "pydicom", "zarr", "numcodecs"):
    datas += copy_metadata(dist)
hiddenimports += collect_submodules("uvicorn") + collect_submodules("skimage")

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
