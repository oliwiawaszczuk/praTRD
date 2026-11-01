"""Python libraries for user nodes: what is bundled, and extra packages from PyPI installed
into <data>/python_packages (appended to sys.path, so the bundled numpy/scipy always win).

Install = two pip runs: a dry-run resolution (`--report`) that sees everything already
importable, then `--no-deps --target` of only what is missing — a package never brings a
second numpy into the app. Version conflicts with bundled libraries are reported, not
"fixed" by replacing them. pip runs in a subprocess (frozen build: the sidecar binary with
`--pip`, see pipmain.py), so a crash or a cancel never touches the sidecar.
"""

import importlib
import importlib.metadata as md
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..jobs import Job

# (distribution, import name, snippet, what for) — shown in the creator's library panel
BUILTIN: tuple[tuple[str, str, str, str], ...] = (
    ("numpy", "numpy", "import numpy as np", "tablice i obliczenia (np jest dostępne od razu)"),
    ("scipy", "scipy", "from scipy import ndimage", "filtry, morfologia, odległości, statystyka"),
    (
        "scikit-image",
        "skimage",
        "from skimage import measure, morphology, filters",
        "segmentacja, etykiety, marching cubes",
    ),
    ("SimpleITK", "SimpleITK", "import SimpleITK as sitk", "filtry ITK, rejestracja, resampling"),
    ("nibabel", "nibabel", "import nibabel as nib", "pliki NIfTI"),
    ("pydicom", "pydicom", "import pydicom", "pliki i tagi DICOM"),
    ("pillow", "PIL", "from PIL import Image", "obrazy 2D"),
    ("fast-simplification", "fast_simplification", "import fast_simplification", "decymacja meshy"),
)

# import name → PyPI name, where they differ (the "install" button after ModuleNotFoundError)
PIP_NAMES = {
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "cv2": "opencv-python-headless",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "nrrd": "pynrrd",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "Bio": "biopython",
    "sitk": "SimpleITK",
}

_SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ]{0,200}$")


class PackageError(Exception):
    pass


def user_dir(root: Path) -> Path:
    return root / "python_packages"


def activate(root: Path) -> None:
    """Make installed packages importable (end of sys.path: bundled libraries win)."""
    d = str(user_dir(root))
    if d not in sys.path:
        sys.path.append(d)
    importlib.invalidate_caches()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _version(dist: str, module: str) -> str:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        mod = sys.modules.get(module)  # never import just to read a version (slow)
        return str(getattr(mod, "__version__", "")) if mod else ""


def _modules(d: md.Distribution) -> list[str]:
    top = d.read_text("top_level.txt")
    if top:
        return [m for m in top.split() if m and not m.startswith("_")]
    out: set[str] = set()
    for f in d.files or []:
        head = f.parts[0]
        if head.endswith((".dist-info", ".data")) or head == "__pycache__" or head.endswith(".pth"):
            continue
        name = head.removesuffix(".py")
        if name.isidentifier() and not name.startswith("_"):
            out.add(name)
    return sorted(out)


def user_packages(root: Path) -> list[dict[str, Any]]:
    d = user_dir(root)
    if not d.is_dir():
        return []
    out = []
    for dist in md.distributions(path=[str(d)]):
        name = dist.metadata["Name"] or "?"
        out.append({"name": name, "version": dist.version, "modules": _modules(dist)})
    return sorted(out, key=lambda x: x["name"].lower())


def can_install() -> bool:
    return importlib.util.find_spec("pip") is not None


def listing(root: Path) -> dict[str, Any]:
    return {
        "builtin": [
            {"name": n, "module": m, "version": _version(n, m), "snippet": s, "about": a}
            for n, m, s, a in BUILTIN
        ],
        "user": user_packages(root),
        "pipNames": PIP_NAMES,
        "canInstall": can_install(),
    }


def _available() -> dict[str, str]:
    """Normalized name → version of every distribution visible on sys.path."""
    out: dict[str, str] = {}
    for d in md.distributions():
        name = d.metadata["Name"]
        if name:
            out.setdefault(_norm(name), d.version)
    return out


def _pip_cmd(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pip", *args]
    return [sys.executable, "-m", "pratrd.custom.pipmain", *args]


def _run_pip(job: Job, args: list[str], target: Path, log: list[str]) -> None:
    env = {**os.environ, "PRATRD_PIP_PATH": str(target), "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    proc = subprocess.Popen(
        _pip_cmd(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.append(line)
                job.report(job.progress, line[-120:])  # also the cancellation point
        if proc.wait() != 0:
            tail = "\n".join(log[-12:])
            raise PackageError(f"pip zakończył się błędem:\n{tail}")
    finally:
        if proc.poll() is None:
            proc.kill()


def install(job: Job, root: Path, spec: str) -> dict[str, Any]:
    spec = spec.strip()
    if not _SPEC.match(spec):
        raise PackageError("Podaj nazwę paczki z PyPI, np. scikit-learn albo trimesh==4.4")
    if not can_install():
        raise PackageError("Instalacja niedostępna: brak pip w tej wersji aplikacji")
    target = user_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        job.report(0.05, "Rozwiązywanie zależności…")
        _run_pip(
            job,
            [
                "install",
                "--dry-run",
                "--quiet",
                "--no-input",
                "--report",
                str(report),
                *spec.split(),
            ],
            target,
            log,
        )
        plan = json.loads(report.read_text(encoding="utf-8")).get("install", [])
    have = _available()
    want, skipped, conflicts = [], [], []
    for item in plan:
        meta = item.get("metadata", {})
        name, ver = meta.get("name", ""), meta.get("version", "")
        if not name:
            continue
        cur = have.get(_norm(name))
        if cur is None:
            want.append(f"{name}=={ver}")
        else:
            skipped.append(name)
            if cur != ver:
                conflicts.append(f"{name}: wbudowana {cur}, paczka chce {ver}")
    if want:
        job.report(0.4, f"Instalowanie: {', '.join(w.split('==')[0] for w in want)}")
        _run_pip(
            job,
            ["install", "--no-deps", "--no-input", "--upgrade", "--target", str(target), *want],
            target,
            log,
        )
    activate(root)
    return {"installed": want, "skipped": skipped, "conflicts": conflicts}


def uninstall(root: Path, name: str) -> None:
    """Remove one distribution from python_packages by its RECORD (pip cannot uninstall
    from a --target directory)."""
    target = user_dir(root)
    for dist in md.distributions(path=[str(target)]):
        if _norm(dist.metadata["Name"] or "") != _norm(name):
            continue
        base = target.resolve()
        dirs: set[Path] = set()
        for f in dist.files or []:
            p = (target / f).resolve()
            if base not in p.parents:
                continue  # RECORD entries outside the folder (e.g. ../bin) are not ours
            if p.is_file() or p.is_symlink():
                p.unlink(missing_ok=True)
            dirs.add(p.parent)
        info = Path(str(dist._path))  # type: ignore[attr-defined]
        shutil.rmtree(info, ignore_errors=True)
        for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
            while d != base and d.is_dir():
                shutil.rmtree(d / "__pycache__", ignore_errors=True)
                if any(d.iterdir()):
                    break
                d.rmdir()
                d = d.parent
        importlib.invalidate_caches()
        return
    raise PackageError(f"Paczka {name} nie jest zainstalowana")
