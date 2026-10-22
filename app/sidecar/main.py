"""PyInstaller entry point for the praTRD sidecar (release builds)."""

import multiprocessing

from pratrd.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for any future multiprocessing in a frozen app
    main()
