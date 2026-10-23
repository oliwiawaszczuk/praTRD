"""Smoke-test a frozen sidecar end to end.

Starts the binary on a spare port with a temp data root, then:
  1. /diagnostics must be ok (every library + DICOM decoder present);
  2. a synthetic 80-slice RLE series is scanned and imported over HTTP — this exercises the
     spawn-based decode pool inside the frozen app, the classic PyInstaller failure point;
  3. one slice is read back and compared voxel-for-voxel.

Usage: python scripts/smoke_sidecar.py <dist_dir>   (dist_dir contains sidecar[.exe])
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from email.message import Message
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.synth import ramp_volume, write_series  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def get(self, path: str, timeout: float = 60) -> tuple[bytes, Message]:
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return r.read(), r.headers  # case-insensitive (uvicorn sends lower-case names)

    def json(self, path: str, body: dict | None = None) -> object:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def wait_job(self, job_id: str, timeout: float = 120) -> dict:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            job = next(j for j in self.json("/jobs") if j["id"] == job_id)  # type: ignore[union-attr]
            if job["state"] in ("done", "error", "cancelled"):
                return job
            time.sleep(0.1)
        raise TimeoutError(job_id)


def check_import(api: Api, data_dir: Path) -> None:
    stored = ramp_volume(80, 24, 20)
    write_series(data_dir, stored, rle=True, bits_stored=16, intercept=0)
    wid = api.json("/workspaces")["active_id"]  # type: ignore[index]
    scan = api.json(f"/workspaces/{wid}/scan", {"paths": [str(data_dir)]})
    res = api.wait_job(scan["jobId"])  # type: ignore[index]
    assert res["state"] == "done", res
    cands = res["result"]["candidates"]
    assert len(cands) == 1 and cands[0]["size"] == [20, 24, 80], cands
    imp = api.json(
        f"/workspaces/{wid}/import",
        {"scanId": res["result"]["scanId"], "ids": [cands[0]["id"]], "anonymize": True},
    )
    t0 = time.monotonic()
    job = api.wait_job(imp["jobIds"][0])  # type: ignore[index]
    assert job["state"] == "done", job
    print(f"import: {time.monotonic() - t0:.2f} s")
    vid = api.json(f"/workspaces/{wid}/volumes")[0]["id"]  # type: ignore[index]
    body, headers = api.get(f"/workspaces/{wid}/volumes/{vid}/slice?axis=k&index=37")
    meta = json.loads(headers["X-Meta"])
    arr = np.frombuffer(body, dtype=np.dtype(meta["dtype"]).newbyteorder("<")).reshape(
        meta["shape"]
    )
    np.testing.assert_array_equal(arr, stored[37])
    thumb, _ = api.get(f"/workspaces/{wid}/volumes/{vid}/thumb.png")
    assert thumb[:8] == b"\x89PNG\r\n\x1a\n"
    check_graph(api, wid, vid)


def check_graph(api: Api, wid: str, vid: str) -> None:
    """Node registry + SimpleITK filters inside the frozen build."""
    types = {t["id"] for t in api.json("/node-types")["types"]}  # type: ignore[index]
    assert {"wolumen/seria", "wolumen/wygladz", "wolumen/resampluj"} <= types, types
    gid = api.json(f"/workspaces/{wid}/graphs")[0]["id"]  # type: ignore[index]
    graph = {
        "nodes": [
            {"id": "a", "type": "wolumen/seria", "params": {"volume": vid}},
            {"id": "b", "type": "wolumen/wygladz", "params": {"method": "median", "radius": 1}},
            {"id": "c", "type": "wolumen/resampluj", "params": {"spacing": 2}},
        ],
        "edges": [
            {"from": "a", "fromSocket": "out", "to": "b", "toSocket": "in"},
            {"from": "b", "fromSocket": "out", "to": "c", "toSocket": "in"},
        ],
    }
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": graph, "targets": ["c"], "quality": "full"},
    )
    job = api.wait_job(r["jobId"])  # type: ignore[index]
    assert job["state"] == "done", job
    res = job["result"]
    assert all(res[n]["state"] == "done" for n in "abc"), res
    ref = res["c"]["outputs"]["out"]["ref"]
    body, headers = api.get(f"/workspaces/{wid}/volumes/{ref}/slice?axis=k&index=-1&fit=8")
    assert body and json.loads(headers["X-Meta"])["shape"]
    print("graph: seria → mediana → resampling OK")

    seg_graph = {
        "nodes": [
            {"id": "a", "type": "wolumen/seria", "params": {"volume": vid}},
            {"id": "t", "type": "segmentacja/prog", "params": {"lo": 4000, "hi": 9000}},
            {"id": "w", "type": "segmentacja/wyspy", "params": {"mode": "largest", "count": 1}},
            {"id": "m", "type": "segmentacja/morfologia", "params": {"op": "close", "radius": 1}},
        ],
        "edges": [
            {"from": "a", "fromSocket": "out", "to": "t", "toSocket": "in"},
            {"from": "t", "fromSocket": "out", "to": "w", "toSocket": "in"},
            {"from": "w", "fromSocket": "out", "to": "m", "toSocket": "in"},
        ],
    }
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": seg_graph, "targets": ["m"], "quality": "full"},
    )
    job = api.wait_job(r["jobId"])  # type: ignore[index]
    assert job["state"] == "done", job
    m = job["result"]["m"]
    assert m["state"] == "done" and m["outputs"]["out"]["kind"] == "segment", m
    assert m["outputs"]["out"]["info"]["voxels"] > 0, m
    print("graph: próg → wyspy → morfologia OK")

    # measurements: marching cubes (skimage) + map_coordinates (scipy) in the frozen build
    meas = {
        "nodes": [
            *seg_graph["nodes"],
            {"id": "s", "type": "pomiary/statystyki", "params": {}},
            {
                "id": "k",
                "type": "pomiary/markupy",
                "params": {"items": [{"id": "l", "type": "line", "p": [[0, 0, 0], [20, 20, 5]]}]},
            },
            {"id": "p", "type": "pomiary/profil", "params": {}},
            {
                "id": "c",
                "type": "segmentacja/edycja",
                "params": {
                    "strokes": [
                        {
                            "kind": "cut",
                            "mode": "keep",
                            "M": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                            "poly": [[-1e4, -1e4], [1e4, -1e4], [1e4, 1e4], [-1e4, 1e4]],
                            "z": None,
                        }
                    ]
                },
            },
        ],
        "edges": [
            *seg_graph["edges"],
            {"from": "m", "fromSocket": "out", "to": "s", "toSocket": "seg"},
            {"from": "a", "fromSocket": "out", "to": "p", "toSocket": "vol"},
            {"from": "k", "fromSocket": "out", "to": "p", "toSocket": "pts"},
            {"from": "m", "fromSocket": "out", "to": "c", "toSocket": "in"},
        ],
    }
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": meas, "targets": ["s", "p", "c"], "quality": "full"},
    )
    job = api.wait_job(r["jobId"])  # type: ignore[index]
    assert job["state"] == "done", job
    st = job["result"]["s"]
    assert st["state"] == "done", st
    row = st["outputs"]["tab"]["value"]["rows"][0]
    assert row["voxels"] == m["outputs"]["out"]["info"]["voxels"] and row["surface"] > 0, row
    assert job["result"]["p"]["state"] == "done", job["result"]["p"]
    # scissors (skimage.draw): "keep" with a polygon around everything changes nothing
    cut = job["result"]["c"]
    assert cut["state"] == "done", cut
    assert cut["outputs"]["out"]["info"]["voxels"] == row["voxels"], cut
    print("graph: statystyki + profil + nożyce OK")

    # meshes: marching cubes, quadric decimation (fast_simplification), voxelisation, export
    mesh = {
        "nodes": [
            *seg_graph["nodes"],
            {"id": "ms", "type": "mesh/z_segmentu", "params": {"smooth": 0.3}},
            {"id": "md", "type": "mesh/decymuj", "params": {"keep": 50}},
            {"id": "mv", "type": "mesh/do_segmentu", "params": {}},
        ],
        "edges": [
            *seg_graph["edges"],
            {"from": "m", "fromSocket": "out", "to": "ms", "toSocket": "in"},
            {"from": "ms", "fromSocket": "out", "to": "md", "toSocket": "in"},
            {"from": "md", "fromSocket": "out", "to": "mv", "toSocket": "in"},
            {"from": "a", "fromSocket": "out", "to": "mv", "toSocket": "vol"},
        ],
    }
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": mesh, "targets": ["mv"], "quality": "full"},
    )
    job = api.wait_job(r["jobId"])  # type: ignore[index]
    assert job["state"] == "done", job
    md = job["result"]["md"]
    assert md["state"] == "done" and md["outputs"]["out"]["info"]["faces"] > 0, md
    assert job["result"]["mv"]["state"] == "done", job["result"]["mv"]
    out = Path(tempfile.gettempdir()) / f"pratrd-smoke-{os.getpid()}.stl"
    api.json(f"/workspaces/{wid}/meshes/{md['outputs']['out']['ref']}/export", {"path": str(out)})
    assert out.stat().st_size > 84, out
    out.unlink()
    print("graph: mesh z segmentu + decymacja + wokselizacja + eksport STL OK")

    # SimpleITK filters (slabs, ITK progress observer, N4, distance map) in the frozen build
    filt = {
        "nodes": [
            *seg_graph["nodes"],
            {"id": "fv", "type": "filtry/naczyniowosc", "params": {"steps": 2}},
            {"id": "fd", "type": "filtry/odszumianie", "params": {"iterations": 2}},
            {"id": "fn", "type": "filtry/n4", "params": {"iterations": 5}},
            {"id": "fm", "type": "filtry/mapa_odleglosci", "params": {}},
        ],
        "edges": [
            *seg_graph["edges"],
            {"from": "a", "fromSocket": "out", "to": "fv", "toSocket": "in"},
            {"from": "a", "fromSocket": "out", "to": "fd", "toSocket": "in"},
            {"from": "a", "fromSocket": "out", "to": "fn", "toSocket": "in"},
            {"from": "m", "fromSocket": "out", "to": "fm", "toSocket": "in"},
        ],
    }
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": filt, "targets": ["fv", "fd", "fn", "fm"], "quality": "full"},
    )
    job = api.wait_job(r["jobId"])  # type: ignore[index]
    assert job["state"] == "done", job
    for nid in ("fv", "fd", "fn", "fm"):
        assert job["result"][nid]["state"] == "done", job["result"][nid]
    print("graph: naczyniowość + dyfuzja + N4 + mapa odległości OK")


def main() -> int:
    dist = Path(sys.argv[1])
    exe = dist / ("sidecar.exe" if os.name == "nt" else "sidecar")
    port = free_port()
    with tempfile.TemporaryDirectory() as root:
        env = {**os.environ, "PRATRD_ROOT": str(Path(root) / "data"), "PRATRD_PORT": str(port)}
        # Log to a file, not a pipe: an unread pipe can fill up and block the sidecar.
        log = Path(root) / "smoke.log"
        log_f = log.open("wb")
        proc = subprocess.Popen([str(exe)], env=env, stdout=log_f, stderr=subprocess.STDOUT)
        api = Api(port)
        try:
            t0 = time.monotonic()
            while True:
                try:
                    api.get("/health", timeout=1)
                    break
                except OSError:
                    if proc.poll() is not None or time.monotonic() - t0 > 90:
                        log_f.flush()
                        print(log.read_text(errors="replace"))
                        print("✗ sidecar did not start")
                        return 1
                    time.sleep(0.1)
            print(f"startup: {time.monotonic() - t0:.2f} s")
            diag = api.json("/diagnostics")
            print(json.dumps(diag, indent=2))
            if not diag.get("ok"):  # type: ignore[union-attr]
                print("✗ diagnostics not ok")
                return 1
            check_import(api, Path(root) / "dicom")
        except Exception as e:  # noqa: BLE001
            log_f.flush()
            print(log.read_text(errors="replace"))
            print(f"✗ {type(e).__name__}: {e}")
            return 1
        finally:
            proc.kill()
            proc.wait()
            log_f.close()
    print("✓ sidecar smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
