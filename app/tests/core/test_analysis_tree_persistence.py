import json
from pathlib import Path

from candyconc.project import Project

# NOTE: Project is a JSON-backed store (project.py:_load). A pre-existing
# 0-byte file (the old NamedTemporaryFile pattern from the SQLite era) is
# treated as a corrupt project file and rejected with "Projektdatei
# unlesbar" — by design. Tests therefore use a path that does not exist yet.


def test_analysis_tree_persisted(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    p = Project(path)
    data = "{\"a\": 1}"
    p.set_analysis_tree(data)
    p.log_op("op1")
    p.close()

    p2 = Project(path)
    assert p2.get_analysis_tree() == data


def test_analysis_tree_snapshot_restore(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    p = Project(path, rotation_ops=5, rotation_bytes=10_000)
    p.set_analysis_tree("{\"b\": 2}")
    for i in range(5):
        p.log_op(f"op{i}")
    p.close()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["analysis_tree"] = None
    path.write_text(json.dumps(data), encoding="utf-8")

    p2 = Project(path)
    assert p2.get_analysis_tree() is None
    ops = p2.timeline()
    assert ops == [f"op{i}" for i in range(5)]
    assert p2.get_analysis_tree() == "{\"b\": 2}"
