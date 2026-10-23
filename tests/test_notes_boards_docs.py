from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pratrd.api.app import create_app
from pratrd.config import Config

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000100e221bc330000000049454e44ae426082"
)


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Config(root=tmp_path / "root", port=0))) as c:
        yield c


def test_notes_crud_title_follows_first_line(client: TestClient) -> None:
    n = client.post("/notes", json={}).json()
    assert n["title"] == "Nowa notatka" and len(n["id"]) == 12
    r = client.put(f"/notes/{n['id']}/data", json={"text": "\n# Pomiary tętniaka\nszyja 4,1 mm"})
    assert r.json()["title"] == "Pomiary tętniaka"
    lst = client.get("/notes").json()["notes"]
    assert lst[0]["preview"].startswith("# Pomiary") and lst[0]["title"] == "Pomiary tętniaka"
    assert client.get(f"/notes/{n['id']}/data").json()["text"].endswith("4,1 mm")
    client.put(f"/notes/{n['id']}", json={"title": "Moja"})
    client.put(f"/notes/{n['id']}/data", json={"text": "inna pierwsza linia"})
    assert client.get("/notes").json()["notes"][0]["title"] == "Moja"  # manual title sticks
    assert client.delete(f"/notes/{n['id']}").json()["ok"]
    assert client.get("/notes").json()["notes"] == []
    assert client.get("/notes/../x/data").status_code in (400, 404)


def test_boards_data_and_assets(client: TestClient, tmp_path: Path) -> None:
    b = client.post("/boards", json={"name": "Tablica 1"}).json()
    bid = b["id"]
    assert client.get(f"/boards/{bid}/data").json()["objects"] == []
    a = client.post(f"/boards/{bid}/assets?ext=png", content=PNG).json()
    assert a["url"].startswith(f"/boards/{bid}/assets/") and a["filename"].endswith(".png")
    got = client.get(a["url"])
    assert (
        got.status_code == 200
        and got.content == PNG
        and "immutable" in got.headers["cache-control"]
    )
    f = tmp_path / "zrzut.png"
    f.write_bytes(PNG)
    assert client.post(f"/boards/{bid}/assets/from-path", json={"path": str(f)}).status_code == 200
    assert client.post(f"/boards/{bid}/assets?ext=exe", content=PNG).status_code == 400
    obj = {"id": "o1", "type": "image", "assetUrl": a["url"], "x": 0, "y": 0}
    client.put(
        f"/boards/{bid}/data", json={"objects": [obj], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    )
    assert client.get(f"/boards/{bid}/data").json()["objects"][0]["assetUrl"] == a["url"]
    client.put(f"/boards/{bid}", json={"name": "Zrzuty"})
    assert client.get("/boards").json()["boards"][0]["name"] == "Zrzuty"
    client.delete(f"/boards/{bid}")
    assert client.get(a["url"]).status_code == 404


def test_app_docs_roundtrip_and_cleaning(client: TestClient) -> None:
    assert client.get("/app_docs").json() == {"tabs": {}, "nodes": {}, "pages": []}
    body = {
        "tabs": {"scena": "# Scena"},
        "nodes": {"segmentacja/prog": "Mój opis"},
        "pages": [{"id": "p1", "title": "Start", "body": "x"}, {"title": "bez id"}],
        "junk": 1,
    }
    client.put("/app_docs", json=body)
    got = client.get("/app_docs").json()
    assert got["nodes"]["segmentacja/prog"] == "Mój opis" and [p["id"] for p in got["pages"]] == [
        "p1"
    ]
    assert "junk" not in got


def test_export_png(client: TestClient, tmp_path: Path) -> None:
    out = tmp_path / "tablica.png"
    assert client.post(f"/export/png?path={out}", content=PNG).status_code == 200
    assert out.read_bytes() == PNG
    assert client.post(f"/export/png?path={tmp_path / 'x.png'}", content=b"nope").status_code == 400
