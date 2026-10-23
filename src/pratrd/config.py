"""Runtime configuration resolved from the environment (set by the Tauri shell)."""

import os
from dataclasses import dataclass
from pathlib import Path

# The Tauri shell picks a free port per launch and passes PRATRD_PORT; the default is
# only for running the sidecar by hand next to `pnpm dev` (praSzczur uses 7432).
DEFAULT_PORT = 7433


@dataclass(frozen=True, slots=True)
class Config:
    root: Path
    port: int

    @property
    def workspaces_dir(self) -> Path:
        return self.root / "workspaces"

    @property
    def app_settings_file(self) -> Path:
        return self.root / "app_settings.json"

    # Global (not per-workspace) like in praSzczur: notes, whiteboards, user docs.
    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def boards_dir(self) -> Path:
        return self.root / "boards"

    @property
    def app_docs_file(self) -> Path:
        return self.root / "app_docs.json"


def from_env() -> Config:
    root = Path(os.environ.get("PRATRD_ROOT", Path.cwd())).resolve()
    port = int(os.environ.get("PRATRD_PORT", DEFAULT_PORT))
    return Config(root=root, port=port)
