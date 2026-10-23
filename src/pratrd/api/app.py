import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import nodes  # noqa: F401 — registers all node types
from ..config import Config
from ..events import EventHub
from ..graph.store import GraphStore
from ..jobs import JobManager
from ..meshes.library import MeshLibrary, cleanup_partials
from ..volumes import store
from ..volumes.library import Library, LibraryError
from ..workspaces import WorkspaceError, WorkspaceStore
from . import (
    app_settings,
    boards,
    docs,
    graphs,
    jobs,
    meshes,
    notes,
    system,
    volumes,
    workspaces,
)

# Origins of the Tauri webview (prod: tauri:// on macOS/Linux, http://tauri.localhost on
# Windows) and of the Vite dev server.
_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


def create_app(config: Config) -> FastAPI:
    hub = EventHub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub.bind_loop(asyncio.get_running_loop())
        for ws_store in config.workspaces_dir.glob("*/store"):
            store.cleanup_partials(ws_store)
            cleanup_partials(ws_store.parent)
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="praTRD sidecar", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.hub = hub
    app.state.jobs = JobManager(hub)
    app.state.workspaces = WorkspaceStore(config.workspaces_dir)
    app.state.library = Library()
    app.state.meshes = MeshLibrary()
    app.state.scans = volumes.ScanCache()
    app.state.graphs = GraphStore()

    # No GZip on purpose: over loopback compression only burns CPU, and binary voxel
    # responses (slices, volumes) are already compact or compressed in the store.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Meta"],
    )

    @app.exception_handler(WorkspaceError)
    async def _ws_error(_: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.exception_handler(LibraryError)
    async def _lib_error(_: Request, exc: LibraryError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    app.include_router(system.router)
    app.include_router(workspaces.router)
    app.include_router(app_settings.router)
    app.include_router(volumes.router)
    app.include_router(meshes.router)
    app.include_router(jobs.router)
    app.include_router(graphs.router)
    app.include_router(notes.router)
    app.include_router(boards.router)
    app.include_router(docs.router)
    return app
