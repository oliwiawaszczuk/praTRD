"""pip entry for installing user-node packages: `python -m pratrd.custom.pipmain …` (dev) or
`<sidecar binary> --pip …` (frozen build, dispatched in app/sidecar/main.py).

PRATRD_PIP_PATH (the python_packages folder) joins sys.path first, so pip's dry-run sees
the packages installed before as installed."""

import os
import sys


def main(argv: list[str]) -> int:
    extra = os.environ.get("PRATRD_PIP_PATH")
    if extra and extra not in sys.path:
        sys.path.append(extra)
    from pip._internal.cli.main import main as pip_main

    return int(pip_main(argv) or 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
