import json
from pathlib import Path

from candyconc.project import Project

# NOTE: Project is a JSON-backed store. The old `p.conn.execute("SELECT op
# FROM timeline")` SQLite surface is gone; the raw (snapshot-compacted)
# timeline is the "timeline" list in the persisted JSON file, which _save()
# rewrites after every log_op/rotation (project.py:_save/_rotate_snapshot).
# A pre-existing empty file is rejected ("Projektdatei unlesbar"), so the
# project path must not exist yet.


def _raw_timeline(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["timeline"]


def test_rotation_after_threshold(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    p = Project(path, rotation_ops=5, rotation_bytes=10_000)
    for i in range(5):
        p.log_op(f"op{i}")
    rows = _raw_timeline(path)
    assert len(rows) == 1
    assert rows[0].startswith("SNAPSHOT:")
    assert p.timeline() == [f"op{i}" for i in range(5)]

    p.log_op("op5")
    p.log_op("op6")
    rows = _raw_timeline(path)
    assert len(rows) == 3
    assert p.timeline() == [f"op{i}" for i in range(7)]


def test_no_rotation_below_threshold(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    p = Project(path, rotation_ops=5, rotation_bytes=10_000)
    for i in range(4):
        p.log_op(f"op{i}")
    rows = _raw_timeline(path)
    assert len(rows) == 4
    assert not any(r.startswith("SNAPSHOT:") for r in rows)
