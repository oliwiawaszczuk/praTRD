"""Performance on large data (E7): runs the real sidecar and measures, per step, wall time and
the peak memory of the whole process tree (sidecar + decode pool).

  uv run python scripts/bench_large.py dicom   # 2000 × 512² CT series (~1 GB, DICOM files)
  uv run python scripts/bench_large.py nifti   # 1000 × 1024² volume (~2 GB, one NIfTI)

Data is synthetic but CT-like (air, body, bone, contrast vessels, noise) so thresholds,
islands and region growing do real work. Everything lives in a temp dir that is removed.
"""

import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.smoke_sidecar import Api, free_port  # noqa: E402
from tests.synth import write_series  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def phantom(nk: int, nj: int, ni: int, seed: int = 0) -> np.ndarray:
    """int16 HU [k, j, i]: air, an elliptic body, a spine, two contrast vessels, noise."""
    rng = np.random.default_rng(seed)
    out = np.empty((nk, nj, ni), np.int16)
    j, i = np.ogrid[:nj, :ni]
    cy, cx = nj / 2, ni / 2
    body = ((i - cx) / (ni * 0.42)) ** 2 + ((j - cy) / (nj * 0.34)) ** 2 <= 1
    spine = (i - cx) ** 2 + (j - cy - nj * 0.18) ** 2 <= (ni * 0.06) ** 2
    for k in range(nk):
        s = np.where(body, 40, -1000).astype(np.int16)
        s[spine] = 900
        # vessels wander slowly along k
        for n, (ox, r) in enumerate(((-0.12, 0.025), (0.12, 0.02))):
            vx = cx + ni * (ox + 0.03 * np.sin(k / (40 + 10 * n)))
            vy = cy - nj * 0.05
            s[(i - vx) ** 2 + (j - vy) ** 2 <= (ni * r) ** 2] = 420
        s += rng.integers(-25, 26, size=s.shape, dtype=np.int16)
        out[k] = s
    return out


class Peak:
    """Peak RSS (MB) of a process and all its descendants, polled every 100 ms."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.peak = 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _tree(self) -> list[str]:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True
        ).stdout
        rows = [r.split() for r in out.splitlines() if r.strip()]
        kids: dict[str, list[str]] = {}
        rss: dict[str, int] = {}
        for pid, ppid, r in rows:
            kids.setdefault(ppid, []).append(pid)
            rss[pid] = int(r)
        todo, seen = [str(self.pid)], []
        while todo:
            p = todo.pop()
            seen.append(p)
            todo.extend(kids.get(p, []))
        return [str(rss.get(p, 0)) for p in seen]

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, sum(int(x) for x in self._tree()) / 1024)
            time.sleep(0.1)

    def reset(self) -> None:
        self.peak = 0.0

    def stop(self) -> None:
        self._stop.set()


RESULTS: list[tuple[str, str, str]] = []


def step(name: str, peak: Peak, fn):
    peak.reset()
    t0 = time.monotonic()
    out = fn()
    dt = time.monotonic() - t0
    time.sleep(0.25)  # one more RSS sample after the work
    RESULTS.append((name, f"{dt:.2f} s", f"{peak.peak:.0f} MB"))
    print(f"  {name}: {dt:.2f} s · peak {peak.peak:.0f} MB", flush=True)
    return out


def run_job(api: Api, r: dict, timeout: float = 1800) -> dict:
    job = api.wait_job(r["jobId"], timeout=timeout)
    assert job["state"] == "done", job
    return job


def slice_times(api: Api, wid: str, vid: str, axis: str, n: int, size: int) -> tuple[float, float]:
    ms = []
    for idx in random.Random(1).sample(range(size), n):
        t0 = time.perf_counter()
        api.get(f"/workspaces/{wid}/volumes/{vid}/slice?axis={axis}&index={idx}&level=0")
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return statistics.median(ms), ms[int(len(ms) * 0.95) - 1]


def evaluate(
    api: Api, wid: str, gid: str, nodes: list, edges: list, targets: list, quality: str
) -> dict:
    r = api.json(
        f"/workspaces/{wid}/graphs/{gid}/evaluate",
        {"graph": {"nodes": nodes, "edges": edges}, "targets": targets, "quality": quality},
    )
    res = run_job(api, r)["result"]
    for t in targets:
        assert res[t]["state"] == "done", (t, res[t])
    return res


def main(kind: str) -> None:
    with tempfile.TemporaryDirectory(dir=os.environ.get("BENCH_TMP")) as tmp:
        tmp = Path(tmp)
        print(f"generating {kind} data…", flush=True)
        t0 = time.monotonic()
        if kind == "dicom":
            vol = phantom(2000, 512, 512)
            write_series(
                tmp / "in",
                (vol + 1024).astype(np.uint16),
                spacing=(0.7, 0.7),
                slice_gap=0.6,
                intercept=-1024,
                bits_stored=12,
                shuffle_seed=None,
            )
            src = tmp / "in"
        else:
            import nibabel as nib

            vol = phantom(1000, 1024, 1024)
            img = nib.Nifti1Image(
                np.ascontiguousarray(vol.transpose(2, 1, 0)), np.diag([0.3, 0.3, 0.3, 1.0])
            )
            src = tmp / "big.nii"
            nib.save(img, src)
        nk, nj, ni = vol.shape
        del vol
        print(f"  data ready in {time.monotonic() - t0:.0f} s", flush=True)

        port = free_port()
        env = {**os.environ, "PRATRD_ROOT": str(tmp / "root"), "PRATRD_PORT": str(port)}
        log = (tmp / "sidecar.log").open("wb")
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "pratrd"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        api = Api(port)
        try:
            for _ in range(300):
                try:
                    api.get("/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            peak = Peak(proc.pid)
            wid = api.json("/workspaces")["active_id"]
            gid = api.json(f"/workspaces/{wid}/graphs")[0]["id"]

            scan = step(
                "skan",
                peak,
                lambda: run_job(api, api.json(f"/workspaces/{wid}/scan", {"paths": [str(src)]})),
            )
            cand = scan["result"]["candidates"][0]

            def do_import():
                r = api.json(
                    f"/workspaces/{wid}/import",
                    {"scanId": scan["result"]["scanId"], "ids": [cand["id"]], "anonymize": True},
                )
                return api.wait_job(r["jobIds"][0], timeout=3600)

            job = step(f"import {ni}×{nj}×{nk}", peak, do_import)
            assert job["state"] == "done", job
            vid = api.json(f"/workspaces/{wid}/volumes")[0]["id"]
            meta = json.loads(api.get(f"/workspaces/{wid}/volumes/{vid}/meta")[0])
            print(f"  levels: {[lv['size'] for lv in meta['levels']]}", flush=True)

            for axis, size in (("k", nk), ("j", nj), ("i", ni)):
                p50, p95 = step(
                    f"przekroje {axis} ×30 (zimne)",
                    peak,
                    lambda a=axis, s=size: slice_times(api, wid, vid, a, 30, s),
                )
                RESULTS[-1] = (RESULTS[-1][0], f"p50 {p50:.0f} / p95 {p95:.0f} ms", RESULTS[-1][2])
            p50, p95 = step(
                "przekroje k ×30 (ciepłe)", peak, lambda: slice_times(api, wid, vid, "k", 30, nk)
            )
            RESULTS[-1] = (RESULTS[-1][0], f"p50 {p50:.0f} / p95 {p95:.0f} ms", RESULTS[-1][2])

            budget = 256 << 20  # default GPU budget (Ustawienia → Wydajność)
            L = next(
                n
                for n, lv in enumerate(meta["levels"])
                if np.prod(lv["size"]) <= budget and max(lv["size"]) <= 2048
            )
            body = step(
                f"wolumen 3D (poziom {L})",
                peak,
                lambda: api.get(f"/workspaces/{wid}/volumes/{vid}/level/{L}", timeout=600)[0],
            )
            RESULTS[-1] = (RESULTS[-1][0] + f" {len(body) >> 20} MB", *RESULTS[-1][1:])
            del body

            nodes = [
                {"id": "s", "type": "wolumen/seria", "params": {"volume": vid}},
                {"id": "t", "type": "segmentacja/prog", "params": {"lo": 300, "hi": 3000}},
                {"id": "w", "type": "segmentacja/wyspy", "params": {"mode": "largest", "count": 2}},
                {"id": "st", "type": "pomiary/statystyki", "params": {}},
            ]
            edges = [
                {"from": "s", "fromSocket": "out", "to": "t", "toSocket": "in"},
                {"from": "t", "fromSocket": "out", "to": "w", "toSocket": "in"},
                {"from": "w", "fromSocket": "out", "to": "st", "toSocket": "seg"},
            ]
            step(
                "graf podgląd: próg → wyspy → statystyki",
                peak,
                lambda: evaluate(api, wid, gid, nodes, edges, ["st"], "preview"),
            )
            res = step(
                "graf pełna: próg → wyspy → statystyki",
                peak,
                lambda: evaluate(api, wid, gid, nodes, edges, ["st"], "full"),
            )
            print(
                f"  segment: {res['st']['outputs']['tab']['value']['rows'][0]['ml']:.1f} ml",
                flush=True,
            )

            g = meta["levels"][0]
            centre = (
                np.asarray(g["origin"])
                + np.asarray(g["direction"]).reshape(3, 3)
                @ (np.asarray(g["spacing"]) * (np.asarray(g["size"]) - 1) / 2)
            ).tolist()
            seed_ijk = np.array(
                [ni / 2 - ni * 0.12 + ni * 0.03 * np.sin(nk / 2 / 40), nj / 2 - nj * 0.05, nk / 2]
            )
            seed = (
                np.asarray(g["origin"])
                + np.asarray(g["direction"]).reshape(3, 3) @ (np.asarray(g["spacing"]) * seed_ijk)
            ).tolist()
            rg = [
                nodes[0],
                {
                    "id": "r",
                    "type": "segmentacja/rozrost",
                    "params": {"seeds": [seed], "method": "tol", "tol": 100},
                },
            ]
            step(
                "graf pełna: region growing (naczynie)",
                peak,
                lambda: evaluate(
                    api,
                    wid,
                    gid,
                    rg,
                    [{"from": "s", "fromSocket": "out", "to": "r", "toSocket": "in"}],
                    ["r"],
                    "full",
                ),
            )

            # scissors from a perspective 3-D camera 600 mm in front, through the whole volume
            c = centre
            M = [1, 0, 0, -c[0], 0, 0, 1, -c[2], 0, 0, 0, 1, 0, 1, 0, 600 - c[1]]
            cut = {
                "kind": "cut",
                "mode": "erase",
                "M": M,
                "poly": [[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]],
                "z": None,
            }
            ed = [
                *nodes[:2],
                {"id": "e", "type": "segmentacja/edycja", "params": {"strokes": [cut]}},
            ]
            ee = [edges[0], {"from": "t", "fromSocket": "out", "to": "e", "toSocket": "in"}]
            step(
                "graf pełna: nożyce 3D (perspektywa)",
                peak,
                lambda: evaluate(api, wid, gid, ed, ee, ["e"], "full"),
            )
        finally:
            peak.stop() if "peak" in locals() else None
            proc.terminate()
            proc.wait(10)

    print(f"\n## {kind}\n\n| krok | czas | szczyt pamięci |\n|---|---|---|")
    for r in RESULTS:
        print(f"| {r[0]} | {r[1]} | {r[2]} |")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dicom")
