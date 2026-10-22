import os
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="posix process model")
def test_sidecar_exits_when_app_pid_dies() -> None:
    # A stand-in "app" process; the watched child must exit within ~1 s of its death.
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    script = "import time, pratrd.watchdog as w; w.start_parent_watchdog(); time.sleep(60)"
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ, "PRATRD_PARENT_PID": str(app.pid)},
    )
    try:
        time.sleep(0.5)
        assert child.poll() is None
        app.kill()
        app.wait()
        assert child.wait(timeout=5) == 0
    finally:
        for p in (app, child):
            if p.poll() is None:
                p.kill()
