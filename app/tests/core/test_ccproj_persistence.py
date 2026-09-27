from pathlib import Path

from candyconc.project import Project

# NOTE: Project is a JSON-backed store (project.py). Two contract changes
# vs. the retired SQLite store that this test was originally written for:
#   1. _load() rejects an existing-but-unparseable file ("Projektdatei
#      unlesbar"), so a pre-created 0-byte NamedTemporaryFile cannot be used
#      as a project path — the path must not exist yet.
#   2. _save() atomically replaces the whole file with this instance's
#      in-memory state (last-writer-wins). There is no cross-instance merge
#      anymore, so persistence is exercised across sequential sessions.


def test_save_load_merge(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    p1 = Project(path)
    p1.log_op("op1")
    p1.add_bookmark({"left": "L1", "kw": "K1", "right": "R1"})
    p1.record_metric("q1", 1)
    p1.close()

    p2 = Project(path)
    p2.log_op("op2")
    p2.add_bookmark({"left": "L2", "kw": "K2", "right": "R2"})
    p2.record_metric("q2", 2)
    p2.close()

    p3 = Project(path)
    assert len(p3.timeline()) == 2
    assert len(p3.bookmarks()) == 2
    df = p3.metrics()
    assert not df.empty
    assert set(df["query"]) == {"q1", "q2"}


def test_description_persisted(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    proj = Project(path)
    proj.set_description("test project")
    proj.close()

    proj2 = Project(path)
    assert proj2.get_description() == "test project"
