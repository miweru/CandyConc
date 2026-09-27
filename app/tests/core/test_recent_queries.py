import json
from pathlib import Path

from candyconc.project import Project

# NOTE: Project rejects a pre-existing empty file ("Projektdatei unlesbar",
# project.py:_load), so the project path must not exist yet.


def test_recent_queries_metrics_and_timeline(tmp_path: Path):
    p = Project(tmp_path / "proj.ccproj")
    p.record_metric("q1", 1)
    p.record_metric("q2", 2)
    p.log_op(json.dumps({"task": "run_query", "term": "q3"}))
    res = p.recent_queries(5)
    assert res[:3] == ["q2", "q1", "q3"]
