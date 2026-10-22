"""Entry point: `uv run python -m pratrd` (dev) or the PyInstaller binary (release)."""

import uvicorn

from .api.app import create_app
from .config import from_env
from .watchdog import start_parent_watchdog


def main() -> None:
    config = from_env()
    config.root.mkdir(parents=True, exist_ok=True)
    start_parent_watchdog()
    uvicorn.run(
        create_app(config),
        host="127.0.0.1",
        port=config.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
