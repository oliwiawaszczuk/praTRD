from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pratrd.api.app import create_app
from pratrd.config import Config


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(root=tmp_path, port=0)))


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["app"] == "praTRD"


def test_first_list_creates_default_workspace(client: TestClient, tmp_path: Path) -> None:
    reg = client.get("/workspaces").json()
    assert len(reg["workspaces"]) == 1
    wid = reg["active_id"]
    assert wid == reg["workspaces"][0]["id"]
    for sub in ("series", "store", "cache", "nodegraphs"):
        assert (tmp_path / "workspaces" / wid / sub).is_dir()
    # idempotent
    assert client.get("/workspaces").json()["active_id"] == wid


def test_crud_and_activate(client: TestClient) -> None:
    first = client.get("/workspaces").json()["active_id"]
    ws = client.post("/workspaces", json={"name": "  CT głowy  "}).json()
    assert ws["name"] == "CT głowy"
    assert client.post(f"/workspaces/{ws['id']}/activate").status_code == 200
    assert client.get("/workspaces").json()["active_id"] == ws["id"]

    assert client.put(f"/workspaces/{ws['id']}", json={"name": "MR"}).json()["name"] == "MR"

    assert client.delete(f"/workspaces/{ws['id']}").status_code == 200
    reg = client.get("/workspaces").json()
    assert reg["active_id"] == first
    assert client.delete(f"/workspaces/{first}").status_code == 400  # last one stays


def test_settings_roundtrip(client: TestClient) -> None:
    wid = client.get("/workspaces").json()["active_id"]
    assert client.get(f"/workspaces/{wid}/settings").json() == {}
    payload = {"activeTab": "scena", "split": 0.62, "nested": {"a": [1, 2]}}
    client.put(f"/workspaces/{wid}/settings", json=payload)
    assert client.get(f"/workspaces/{wid}/settings").json() == payload


def test_path_traversal_rejected(client: TestClient) -> None:
    assert client.get("/workspaces/..%2F..%2Fetc/settings").status_code == 404
    assert client.put("/workspaces/abc/settings", json={}).status_code == 404


def test_export_import_skips_cache(client: TestClient, tmp_path: Path) -> None:
    wid = client.get("/workspaces").json()["active_id"]
    client.put(f"/workspaces/{wid}/settings", json={"k": 1})
    (tmp_path / "workspaces" / wid / "cache" / "big.bin").write_bytes(b"x" * 10)

    dest = tmp_path / "out"
    dest.mkdir()
    r = client.post(f"/workspaces/{wid}/export", json={"dest_dir": str(dest)})
    out = Path(r.json()["path"])
    assert not (out / "cache").exists()
    # exporting twice must not silently overwrite
    assert client.post(f"/workspaces/{wid}/export", json={"dest_dir": str(dest)}).status_code == 409

    imported = client.post("/workspaces/import", json={"src_dir": str(out)}).json()
    assert imported["id"] != wid
    assert client.get(f"/workspaces/{imported['id']}/settings").json() == {"k": 1}
    assert (tmp_path / "workspaces" / imported["id"] / "cache").is_dir()

    bad = tmp_path / "not_a_ws"
    bad.mkdir()
    assert client.post("/workspaces/import", json={"src_dir": str(bad)}).status_code == 400


def test_concurrent_creates_lose_nothing(client: TestClient) -> None:
    client.get("/workspaces")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: client.post("/workspaces", json={"name": f"w{i}"}), range(24)))
    assert len(client.get("/workspaces").json()["workspaces"]) == 25


def test_app_settings_roundtrip(client: TestClient) -> None:
    assert client.get("/app_settings").json() == {}
    client.put("/app_settings", json={"gpuBudgetVoxels": 256**3})
    assert client.get("/app_settings").json() == {"gpuBudgetVoxels": 256**3}


def test_diagnostics_all_deps_present(client: TestClient) -> None:
    d = client.get("/diagnostics").json()
    assert d["ok"], d
