import json
import threading
from pathlib import Path

from candyconc.project import Project

# NOTE: Project rejects a pre-existing empty file ("Projektdatei unlesbar",
# project.py:_load), so the project path must not exist yet. Replay of a
# run_query op posts to the backend URL; an unreachable backend is swallowed
# (project.py:_apply_op catches httpx.HTTPError when no sha256 is expected),
# so these tests run offline.


def test_project_replay_runs_ops(tmp_path: Path):
    p = Project(tmp_path / "proj.ccproj")
    p.log_op(json.dumps({"task": "run_query", "term": "fox", "ctx": 2}))
    p.replay()


def test_project_replay_abort(tmp_path: Path):
    p = Project(tmp_path / "proj.ccproj")
    for _ in range(5):
        p.log_op(json.dumps({"task": "run_query", "term": "fox", "ctx": 1}))
    ev = threading.Event()
    count = 0

    def cb(i, total):
        nonlocal count
        count = i
        if i == 2:
            ev.set()

    p.replay(stop_event=ev, callback=cb)
    assert count <= 2
