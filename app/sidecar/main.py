"""PyInstaller entry point for the praTRD sidecar (release builds)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for any future multiprocessing in a frozen app
    if len(sys.argv) > 1 and sys.argv[1] == "--pip":  # packages for user nodes (Kreator)
        from pratrd.custom.pipmain import main as pip_main

        sys.exit(pip_main(sys.argv[2:]))
    from pratrd.__main__ import main

    main()
