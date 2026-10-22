import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pratrd.api.app import create_app
from pratrd.config import Config

from .synth import ramp_volume, write_series


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Config(root=tmp_path / "root", port=0))) as c:
        yield c


def _wait(client: TestClient, job_id: str, timeout: float = 30) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        job = next(j for j in client.get("/jobs").json() if j["id"] == job_id)
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.02)
    raise TimeoutError(job_id)


def test_scan_import_list_slice_delete(client: TestClient, tmp_path: Path) -> None:
    stored = ramp_volume(6, 5, 4)
    write_series(tmp_path / "in", stored)
    wid = client.get("/workspaces").json()["active_id"]

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        scan_job = client.post(f"/workspaces/{wid}/scan", json={"paths": [str(tmp_path / "in")]})
        res = _wait(client, scan_job.json()["jobId"])["result"]
        (cand,) = res["candidates"]
        assert cand["size"] == [4, 5, 6] and not cand["alreadyImported"]

        r = client.post(
            f"/workspaces/{wid}/import",
            json={"scanId": res["scanId"], "ids": [cand["id"]], "anonymize": True},
        )
        (jid,) = r.json()["jobIds"]
        assert _wait(client, jid)["state"] == "done"
        # The socket saw job events and the library-changed event.
        seen = set()
        while "library" not in seen:
            msg = ws.receive_json()
            seen.add(msg["type"])
        assert "job" in seen

    (vol,) = client.get(f"/workspaces/{wid}/volumes").json()
    assert vol["patientName"].startswith("ANON-") and vol["planes"]["k"] == "osiowy"
    vid = vol["id"]

    s = client.get(f"/workspaces/{wid}/volumes/{vid}/slice", params={"axis": "k", "index": 2})
    meta = json.loads(s.headers["X-Meta"])
    arr = np.frombuffer(s.content, dtype=np.dtype(meta["dtype"]).newbyteorder("<"))
    np.testing.assert_array_equal(arr.reshape(meta["shape"]), stored[2].astype(np.int32) - 1024)
    s = client.get(f"/workspaces/{wid}/volumes/{vid}/slice", params={"axis": "i", "index": 1})
    assert json.loads(s.headers["X-Meta"])["shape"] == [6, 5]

    assert client.get(f"/workspaces/{wid}/volumes/{vid}/thumb.png").status_code == 200
    tags = client.get(f"/workspaces/{wid}/volumes/{vid}/tags").json()
    assert any(t["name"] == "Modality" for t in tags)
    assert client.get(f"/workspaces/{wid}/volumes/{vid}/meta").json()["levels"][0]["size"] == [
        4,
        5,
        6,
    ]

    # Re-scan flags the series as already imported.
    j = client.post(f"/workspaces/{wid}/scan", json={"paths": [str(tmp_path / "in")]}).json()
    assert _wait(client, j["jobId"])["result"]["candidates"][0]["alreadyImported"]

    assert (
        client.put(f"/workspaces/{wid}/volumes/{vid}", json={"name": "Głowa"}).json()["name"]
        == "Głowa"
    )
    assert client.delete(f"/workspaces/{wid}/volumes/{vid}").status_code == 200
    assert client.get(f"/workspaces/{wid}/volumes").json() == []
    assert client.get(f"/workspaces/{wid}/volumes/{vid}/slice").status_code == 404


def test_bad_ids_rejected(client: TestClient) -> None:
    wid = client.get("/workspaces").json()["active_id"]
    assert client.get(f"/workspaces/{wid}/volumes/../../x/meta").status_code == 404
    assert client.get("/workspaces/deadbeef0000/volumes").status_code == 404
    r = client.post(f"/workspaces/{wid}/import", json={"scanId": "nope", "ids": [0]})
    assert r.status_code == 404


def test_partial_imports_cleaned_on_startup(tmp_path: Path) -> None:
    root = tmp_path / "root"
    with TestClient(create_app(Config(root=root, port=0))) as c:
        wid = c.get("/workspaces").json()["active_id"]
    partial = root / "workspaces" / wid / "store" / "abc.zarr.partial"
    partial.mkdir(parents=True)
    with TestClient(create_app(Config(root=root, port=0))):
        assert not partial.exists()


def test_export_csv_writes_utf8_bom(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "wyniki.csv"
    r = client.post("/export/csv", json={"path": str(target), "text": "Objętość;mm³\n1;2\n"})
    assert r.status_code == 200
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "mm³" in target.read_text(encoding="utf-8-sig")
    bad = client.post("/export/csv", json={"path": str(tmp_path / "x.sh"), "text": ""})
    assert bad.status_code == 400
