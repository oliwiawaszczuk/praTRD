# ruff: noqa: F811 — `setup` is a fixture imported from test_graph
from pathlib import Path

import numpy as np
import pytest

from pratrd.custom import manifest as mf
from pratrd.custom.store import CustomNodeError, CustomNodeStore
from pratrd.custom.tester import run_test
from pratrd.graph.types import REGISTRY, schema, unregister
from pratrd.jobs import Job

from .test_graph import edge, node, run, setup  # noqa: F401, F811 — fixture


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for t in [t for t in REGISTRY if t.startswith(mf.PREFIX)]:
        unregister(t)


def manifest(**over) -> dict:
    m = {
        "slug": "prog",
        "label": "Mój próg",
        "domain": "segmentacja",
        "inputs": [{"id": "ct", "label": "CT", "kind": "wolumen"}],
        "outputs": [{"id": "maska", "label": "Maska", "kind": "segment"}],
        "params": [
            {
                "key": "prog",
                "label": "Próg",
                "type": "number",
                "default": 100,
                "min": -1000,
                "max": 3000,
                "unit": "HU",
            }
        ],
    }
    return {**m, **over}


THRESHOLD = """\
def run(inputs, params, ctx):
    print("threshold", params.prog)
    return inputs.ct.array > params.prog
"""


def test_saved_node_runs_in_graph(setup, tmp_path: Path) -> None:
    ev, vid, data, _ = setup
    st = CustomNodeStore(tmp_path / "custom_nodes")
    st.save(manifest(), THRESHOLD, None)
    nt = REGISTRY["wlasne/prog"]
    assert nt.custom and nt.domain == "segmentacja" and nt.stage == "przetwarzanie"
    s = next(t for t in schema()["types"] if t["id"] == "wlasne/prog")  # GET /node-types
    assert s["custom"] and s["params"][0]["unit"] == "HU"
    g = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wlasne/prog", prog=500)],
        "edges": [edge("a", "b", ts="ct")],
    }
    res = run(ev, g, ["b"])
    assert res["b"]["state"] == "done", res["b"]
    out = res["b"]["outputs"]["maska"]
    assert out["kind"] == "segment" and out["info"]["ref"] == vid
    assert out["info"]["voxels"] == int(np.count_nonzero(data > 500))

    # a fresh store (= restart) registers it again from disk
    unregister("wlasne/prog")
    CustomNodeStore(tmp_path / "custom_nodes").load_all()
    assert run(ev, g, ["b"])["b"]["state"] == "done"


def test_version_follows_code_not_labels() -> None:
    m = mf.clean(manifest())
    v = mf.version_of(m, THRESHOLD)
    assert v == mf.version_of(mf.clean(manifest(label="Inna nazwa")), THRESHOLD)
    assert v != mf.version_of(m, THRESHOLD + "\n# zmiana\n")
    assert v < 2**53


def test_error_points_at_user_line(setup, tmp_path: Path) -> None:
    ev, vid, _, _ = setup
    st = CustomNodeStore(tmp_path / "c")
    st.save(manifest(), "def run(inputs, params, ctx):\n    x = 1\n    return x / 0\n", None)
    g = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wlasne/prog")],
        "edges": [edge("a", "b", ts="ct")],
    }
    res = run(ev, g, ["b"])["b"]
    assert res["state"] == "error" and res["error"].startswith("Linia 3: ZeroDivisionError")


def test_read_only_input_hint(setup, tmp_path: Path) -> None:
    ev, vid, _, _ = setup
    st = CustomNodeStore(tmp_path / "c")
    code = (
        "def run(inputs, params, ctx):\n    a = inputs.ct.array\n    a[0] = 1\n    return a > 0\n"
    )
    st.save(manifest(), code, None)
    g = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wlasne/prog")],
        "edges": [edge("a", "b", ts="ct")],
    }
    assert ".copy()" in run(ev, g, ["b"])["b"]["error"]


@pytest.mark.parametrize(
    "over, msg",
    [
        ({"slug": "Zły"}, "Identyfikator"),
        ({"outputs": []}, "co najmniej jedno wyjście"),
        ({"inputs": [{"id": "a", "kind": "wolumen"}, {"id": "a", "kind": "mesh"}]}, "dwa razy"),
        ({"inputs": [{"id": "class", "kind": "wolumen"}]}, "Wejście"),
        ({"inputs": [{"id": "a", "kind": "obraz"}]}, "nieznany rodzaj"),
        ({"params": [{"key": "a", "type": "select", "options": []}]}, "opcji"),
        ({"params": [{"key": "a", "type": "number", "min": 5, "max": 1}]}, "min"),
        ({"domain": "xyz"}, "kategoria"),
    ],
)
def test_manifest_validation(over: dict, msg: str) -> None:
    with pytest.raises(mf.ManifestError, match=msg):
        mf.clean(manifest(**over))


def test_param_defaults_are_clamped() -> None:
    m = mf.clean(manifest(params=[{"key": "n", "type": "int", "default": 9.6, "max": 5}]))
    assert m["params"][0]["default"] == 5
    m = mf.clean(
        manifest(params=[{"key": "s", "type": "select", "default": "zz", "options": ["a", "b"]}])
    )
    assert m["params"][0]["default"] == "a"


def test_rename_and_conflicts(tmp_path: Path) -> None:
    st = CustomNodeStore(tmp_path / "c")
    st.save(manifest(), THRESHOLD, None)
    st.save(manifest(slug="inny"), THRESHOLD, None)
    with pytest.raises(CustomNodeError) as e:
        st.save(manifest(slug="inny"), THRESHOLD, "prog")  # rename onto an existing node
    assert e.value.status == 409
    st.save(manifest(slug="nowy"), THRESHOLD, "prog")
    assert "wlasne/prog" not in REGISTRY and "wlasne/nowy" in REGISTRY
    assert {n["slug"] for n in st.list()} == {"inny", "nowy"}
    with pytest.raises(CustomNodeError):
        st.save(manifest(slug="inny"), THRESHOLD, None)  # new node with a taken name
    st.delete("inny")
    assert "wlasne/inny" not in REGISTRY


def test_export_import_roundtrip(tmp_path: Path) -> None:
    st = CustomNodeStore(tmp_path / "c")
    st.save(manifest(), THRESHOLD, None)
    f = tmp_path / "prog.pratrdnode"
    st.export("prog", f)
    d = CustomNodeStore(tmp_path / "other").read_file(f)
    assert d["code"] == THRESHOLD and d["manifest"]["label"] == "Mój próg" and not d["exists"]
    assert st.read_file(f)["exists"]


def test_broken_manifest_on_disk_is_listed_not_registered(tmp_path: Path) -> None:
    d = tmp_path / "c" / "zepsuty"
    d.mkdir(parents=True)
    (d / "node.json").write_text('{"label": "x", "outputs": []}')
    st = CustomNodeStore(tmp_path / "c")
    st.load_all()
    assert "wlasne/zepsuty" not in REGISTRY
    assert st.list()[0]["error"]


EVERYTHING = """\
import numpy as np
from scipy import ndimage

def run(inputs, params, ctx):
    ct, kula, siatka = inputs.ct, inputs.kula, inputs.siatka
    ctx.progress(0.5)
    dist = ndimage.distance_transform_edt(kula.array == 0, sampling=kula.spacing_kji)
    lab = np.zeros(ct.shape, np.uint8)
    lab[kula.array > 0] = 1
    lab[(dist > 0) & (dist < 2)] = 2
    v, f = siatka.verts, siatka.faces
    print("triangles", len(f))
    return {
        "odl": dist,                      # float64 -> float32
        "ile": float((ct.array > 200).sum()),
        "tab": [{"obszar": r["name"], "ml": r["ml"]} for r in inputs.tab["rows"]],
        "mesh": (v + 1.0, f),
        "lab": ctx.volume(lab, like=ct, labels=["Kula", "Pierścień"]),
        "pkt": [[0, 0, 0], [1, 2, 3]],
    }

def test(result, inputs, params):
    assert result["ile"] > 0
    assert result["ile"] < 0, "celowo nie przechodzi"
"""


def test_tester_on_phantom_every_kind(setup) -> None:
    ev, *_ = setup
    m = manifest(
        inputs=[
            {"id": "ct", "kind": "wolumen"},
            {"id": "kula", "kind": "segment"},
            {"id": "siatka", "kind": "mesh"},
            {"id": "tab", "kind": "tabela"},
        ],
        outputs=[
            {"id": "odl", "kind": "wolumen"},
            {"id": "ile", "kind": "liczba"},
            {"id": "tab", "kind": "tabela"},
            {"id": "mesh", "kind": "mesh"},
            {"id": "lab", "kind": "segmentacja"},
            {"id": "pkt", "kind": "punkty"},
        ],
        params=[],
    )
    r = run_test(Job("j", "t", "t", "w"), ev, {"manifest": m, "code": EVERYTHING})
    assert r["state"] == "done", r["error"]
    o = r["outputs"]
    assert o["odl"]["kind"] == "wolumen" and r["stats"]["odl"]["converted"] == "float32"
    assert o["ile"]["value"] > 0
    assert [c["key"] for c in o["tab"]["value"]["columns"]] == ["obszar", "ml"]
    assert o["mesh"]["info"]["faces"] > 100 and o["mesh"]["info"]["ref"]
    assert [lb["name"] for lb in o["lab"]["info"]["labels"]] == ["Kula", "Pierścień"]
    assert len(o["pkt"]["value"]["items"]) == 2
    assert r["logs"][0].startswith("triangles")
    assert set(r["inputs"]) == {"ct", "kula", "siatka", "tab"}
    user = next(c for c in r["checks"] if c["id"] == "user")
    assert user["level"] == "fail" and user["message"] == "celowo nie przechodzi"
    assert user["line"] == 24

    # the test always runs (prints come back), even with the same code and inputs
    r2 = run_test(Job("j", "t", "t", "w"), ev, {"manifest": m, "code": EVERYTHING})
    assert r2["logs"] == r["logs"]


@pytest.mark.parametrize(
    "code, msg",
    [
        ("def run(inputs, params, ctx):\n  return 1\n", "oczekiwano tablicy"),
        ("def run(inputs, params, ctx):\n  return {'zle': 1}\n", "Nieznane wyjście"),
        ("def run(inputs, params, ctx):\n  return {}\n", "Brak wyjścia"),
        ("def run(inputs, params, ctx):\n  return inputs.ct.array[:5] > 0\n", "nie pasuje"),
        ("def run(inputs, params, ctx):\n  return inputs.xx\n", "dostępne: ct"),
        ("import torch_nope\ndef run(inputs, params, ctx):\n  pass\n", "panelu Biblioteki"),
        ("def not_run():\n  pass\n", "Brak funkcji run"),
        ("def run(inputs, params, ctx)\n  pass\n", "Błąd składni"),
    ],
)
def test_tester_reports_mistakes(setup, code: str, msg: str) -> None:
    ev, *_ = setup
    r = run_test(Job("j", "t", "t", "w"), ev, {"manifest": manifest(), "code": code})
    assert r["state"] != "done"
    assert msg in r["error"]["message"]


def test_tester_checks_empty_and_nan(setup) -> None:
    ev, vid, *_ = setup
    code = "def run(inputs, params, ctx):\n    return inputs.ct.array < -5000\n"
    r = run_test(
        Job("j", "t", "t", "w"),
        ev,
        {"manifest": manifest(), "code": code, "inputs": {"ct": {"source": "seria", "vid": vid}}},
    )
    assert r["state"] == "done"
    assert any(c["level"] == "warn" and "Pusty" in c["message"] for c in r["checks"])
    m = manifest(outputs=[{"id": "o", "kind": "wolumen"}])
    code = "import numpy as np\ndef run(inputs, params, ctx):\n    return inputs.ct.array / 0.0\n"
    r = run_test(Job("j", "t", "t", "w"), ev, {"manifest": m, "code": code})
    assert any(c["level"] == "fail" and "NaN" in c["message"] for c in r["checks"])
    assert any("linia 3" in ln and "divide" in ln for ln in r["logs"])


def test_tester_uses_graph_node_as_input(setup) -> None:
    ev, vid, data, _ = setup
    graph = {
        "nodes": [node("a", "wolumen/seria", volume=vid), node("b", "wolumen/wygladz", sigma=1)],
        "edges": [edge("a", "b")],
    }
    r = run_test(
        Job("j", "t", "t", "w"),
        ev,
        {
            "manifest": manifest(),
            "code": THRESHOLD,
            "graph": graph,
            "inputs": {"ct": {"source": "graf", "node": "b", "socket": "out"}},
        },
    )
    assert r["state"] == "done", r["error"]
    assert r["inputs"]["ct"]["info"]["name"].endswith("wygładzony") or r["inputs"]["ct"]["ref"]


def test_missing_module_is_named(setup) -> None:
    ev, *_ = setup
    code = "import sklearn.cluster\ndef run(inputs, params, ctx):\n  pass\n"
    r = run_test(Job("j", "t", "t", "w"), ev, {"manifest": manifest(), "code": code})
    assert r["error"]["module"] == "sklearn" and r["error"]["line"] == 1


def test_libraries_listing_and_uninstall(tmp_path: Path) -> None:
    from pratrd.custom import packages

    lst = packages.listing(tmp_path)
    np_entry = next(b for b in lst["builtin"] if b["module"] == "numpy")
    assert np_entry["version"] == np.__version__ and lst["canInstall"]
    assert lst["user"] == []

    # what pip --target leaves behind: package + dist-info with RECORD
    d = packages.user_dir(tmp_path)
    (d / "toy_pkg").mkdir(parents=True)
    (d / "toy_pkg" / "__init__.py").write_text("VALUE = 7\n")
    info = d / "toy_pkg-1.2.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: toy-pkg\nVersion: 1.2\n")
    (info / "RECORD").write_text(
        "toy_pkg/__init__.py,,\ntoy_pkg-1.2.dist-info/METADATA,,\n"
        "toy_pkg-1.2.dist-info/RECORD,,\n../../outside.txt,,\n"
    )
    (tmp_path / "outside.txt").write_text("not ours")
    packages.activate(tmp_path)
    try:
        import toy_pkg  # type: ignore[import-not-found]

        assert toy_pkg.VALUE == 7
        assert packages.listing(tmp_path)["user"] == [
            {"name": "toy-pkg", "version": "1.2", "modules": ["toy_pkg"]}
        ]
        packages.uninstall(tmp_path, "Toy_Pkg")
        assert not any(d.iterdir()) and (tmp_path / "outside.txt").exists()
        with pytest.raises(packages.PackageError):
            packages.uninstall(tmp_path, "toy-pkg")
    finally:
        import sys

        sys.path.remove(str(d))
        sys.modules.pop("toy_pkg", None)


@pytest.mark.parametrize("spec", ["", "-r /etc/passwd", "pkg; rm -rf /", "--index-url x y"])
def test_install_rejects_odd_specs(tmp_path: Path, spec: str) -> None:
    from pratrd.custom import packages

    with pytest.raises(packages.PackageError, match="PyPI"):
        packages.install(Job("j", "t", "t", "w"), tmp_path, spec)
