"""Exit when the Tauri shell that spawned us is gone (crash, force-quit, kill -9).

Replaces "kill whatever holds the port on next start": an orphaned sidecar never
outlives its app, so nothing ever needs to be killed blindly.
"""

import os
import sys
import threading
import time


def _watch_posix(app_pid: int) -> None:
    # Probe the app PID itself, not getppid(): in dev the direct parent is `uv run`,
    # which can survive the app (and a SIGKILL to uv does not reach its child).
    while True:
        try:
            os.kill(app_pid, 0)
        except ProcessLookupError:
            os._exit(0)
        except PermissionError:
            pass  # exists, owned by someone else — cannot happen for our own parent
        time.sleep(1.0)


def _watch_windows(app_pid: int) -> None:
    import ctypes

    synchronize, infinite = 0x00100000, 0xFFFFFFFF
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(synchronize, False, app_pid)
    if not handle:
        os._exit(0)  # parent already gone
    k32.WaitForSingleObject(handle, infinite)
    os._exit(0)


def start_parent_watchdog() -> None:
    raw = os.environ.get("PRATRD_PARENT_PID")
    if not raw:
        return  # started by hand / tests
    target = _watch_windows if sys.platform == "win32" else _watch_posix
    threading.Thread(target=target, args=(int(raw),), daemon=True, name="parent-watchdog").start()
