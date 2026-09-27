import json
from pathlib import Path

from candyconc.project import Project

# NOTE: Project rejects a pre-existing empty file ("Projektdatei unlesbar",
# project.py:_load), so the project path must not exist yet.


def test_undo_last(tmp_path: Path):
    p = Project(tmp_path / "proj.ccproj")
    p.log_op(json.dumps({"task": "run_query", "term": "fox"}))
    p.log_op(json.dumps({"task": "run_query", "term": "dog"}))
    assert len(p.timeline()) == 2
    p.undo_last()
    ops = p.timeline()
    assert len(ops) == 1
    assert "fox" in ops[0]
