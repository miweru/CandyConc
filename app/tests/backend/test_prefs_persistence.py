import pytest

from candyconc.services.backend import prefs


def _reset_store(monkeypatch, tmp_path):
    monkeypatch.setattr(prefs, "_PREFS_PATH", tmp_path / "prefs.json")
    prefs._PREFS.clear()
    prefs._BOOKMARKS.clear()
    prefs._LISTENERS.clear()
    monkeypatch.setattr(prefs, "_LOADED", False)


def test_prefs_survive_store_reload(tmp_path, monkeypatch):
    _reset_store(monkeypatch, tmp_path)

    prefs.set_pref("bob:default", "theme", "forest")
    prefs.add_bookmark("bob:default", {"left": "a", "kw": "b", "right": "c"})

    prefs._PREFS.clear()
    prefs._BOOKMARKS.clear()
    monkeypatch.setattr(prefs, "_LOADED", False)

    state = prefs.get_state("bob:default")
    assert state["prefs"]["theme"] == "forest"
    assert state["bookmarks"] == [{"left": "a", "kw": "b", "right": "c"}]


def test_empty_bookmarks_are_persisted(tmp_path, monkeypatch):
    _reset_store(monkeypatch, tmp_path)

    row = {"left": "a", "kw": "b", "right": "c"}
    prefs.add_bookmark("bob:default", row)
    prefs.remove_bookmark("bob:default", row)

    prefs._PREFS.clear()
    prefs._BOOKMARKS.clear()
    monkeypatch.setattr(prefs, "_LOADED", False)

    assert prefs.get_state("bob:default")["bookmarks"] == []


def test_prefs_reject_unknown_keys_atomically(tmp_path, monkeypatch):
    _reset_store(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="unsupported preference key"):
        prefs.set_prefs("bob:default", {"theme": "forest", "rawSecret": "token"})

    assert prefs.get_state("bob:default")["prefs"] == {}


def test_prefs_reject_oversized_values(tmp_path, monkeypatch):
    _reset_store(monkeypatch, tmp_path)
    monkeypatch.setattr(prefs, "MAX_PREF_VALUE_BYTES", 4)

    with pytest.raises(ValueError, match="exceeds"):
        prefs.set_pref("bob:default", "theme", "forest")

    assert prefs.get_state("bob:default")["prefs"] == {}


def test_prefs_enforce_update_key_limit(tmp_path, monkeypatch):
    _reset_store(monkeypatch, tmp_path)
    monkeypatch.setattr(prefs, "MAX_PREF_UPDATE_KEYS", 1)

    with pytest.raises(ValueError, match="at most"):
        prefs.set_prefs("bob:default", {"theme": "forest", "language": "de"})

    assert prefs.get_state("bob:default")["prefs"] == {}
