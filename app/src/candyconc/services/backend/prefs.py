from typing import Any, AsyncGenerator, Dict, List, Mapping, Set, Tuple
import asyncio
import contextlib
import json
import os
from pathlib import Path
from threading import RLock

from candyconc.paths import data_dir

# Durable user preferences and bookmark store. The listener queues remain
# process-local, but preferences/bookmarks survive backend restarts.

_PREFS: Dict[str, Dict[str, str]] = {}
_BOOKMARKS: Dict[str, Set[Tuple[str, str, str]]] = {}
_LISTENERS: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
_LOCK = RLock()
_LOADED = False
_PREFS_PATH = Path(
    os.environ.get("CANDYCONC_PREFS_PATH", data_dir() / "prefs.json")
)

ALLOWED_PREF_KEYS: Set[str] = {
    "activeEmbedding",
    "autoSaveBookmarks",
    "backgroundResearch",
    "bookmarks_json",
    "confirmDelete",
    "defaultContext",
    "defaultCorpus",
    "enableShortcuts",
    "fontFamily",
    "fontSize",
    "highlightColor",
    "language",
    "resultsPerPage",
    "showLineNumbers",
    "theme",
}
MAX_PREF_KEYS_PER_USER = 32
MAX_PREF_UPDATE_KEYS = 16
MAX_PREF_VALUE_BYTES = 16 * 1024


def _validate_pref_key(key: str) -> str:
    if not isinstance(key, str) or key not in ALLOWED_PREF_KEYS:
        raise ValueError(f"unsupported preference key: {key!r}")
    return key


def _validate_pref_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("preference values must be strings")
    if len(value.encode("utf-8")) > MAX_PREF_VALUE_BYTES:
        raise ValueError(
            f"preference value exceeds {MAX_PREF_VALUE_BYTES} bytes"
        )
    return value


def _validated_pref_update(updates: Mapping[str, str]) -> Dict[str, str]:
    if len(updates) > MAX_PREF_UPDATE_KEYS:
        raise ValueError(
            f"preference update may include at most {MAX_PREF_UPDATE_KEYS} keys"
        )
    validated: Dict[str, str] = {}
    for key, value in updates.items():
        validated[_validate_pref_key(key)] = _validate_pref_value(value)
    return validated


def _load_locked() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not _PREFS_PATH.is_file():
        return
    try:
        data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    prefs = data.get("prefs")
    if isinstance(prefs, dict):
        for user, raw in prefs.items():
            if not isinstance(user, str) or not isinstance(raw, dict):
                continue
            parsed: Dict[str, str] = {}
            for key, value in raw.items():
                if len(parsed) >= MAX_PREF_KEYS_PER_USER:
                    break
                try:
                    parsed[_validate_pref_key(key)] = _validate_pref_value(str(value))
                except ValueError:
                    continue
            _PREFS[user] = parsed
    bookmarks = data.get("bookmarks")
    if isinstance(bookmarks, dict):
        for user, rows in bookmarks.items():
            if not isinstance(user, str) or not isinstance(rows, list):
                continue
            parsed: set[tuple[str, str, str]] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                left = row.get("left")
                kw = row.get("kw")
                right = row.get("right")
                if all(isinstance(part, str) for part in (left, kw, right)):
                    parsed.add((left, kw, right))
            _BOOKMARKS[user] = parsed


def _save_locked() -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "prefs": _PREFS,
        "bookmarks": {
            user: [
                {"left": left, "kw": kw, "right": right}
                for left, kw, right in sorted(rows)
            ]
            for user, rows in _BOOKMARKS.items()
        },
    }
    tmp = _PREFS_PATH.with_name(f"{_PREFS_PATH.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, _PREFS_PATH)


def register(user: str) -> asyncio.Queue[Dict[str, Any]]:
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    _LISTENERS.setdefault(user, []).append(q)
    return q


def unregister(user: str, q: asyncio.Queue[Dict[str, Any]]) -> None:
    with contextlib.suppress(ValueError):
        if user in _LISTENERS:
            _LISTENERS[user].remove(q)
            if not _LISTENERS[user]:
                _LISTENERS.pop(user, None)


def _notify(user: str) -> None:
    state = get_state(user)
    for q in list(_LISTENERS.get(user, [])):
        loop = getattr(q, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(q.put_nowait, state)
        else:
            q.put_nowait(state)


def set_pref(user: str, key: str, value: str) -> None:
    set_prefs(user, {key: value})


def set_prefs(user: str, updates: Mapping[str, str]) -> None:
    validated = _validated_pref_update(updates)
    with _LOCK:
        _load_locked()
        current = dict(_PREFS.get(user, {}))
        if len(set(current) | set(validated)) > MAX_PREF_KEYS_PER_USER:
            raise ValueError(
                f"user may store at most {MAX_PREF_KEYS_PER_USER} preferences"
            )
        current.update(validated)
        _PREFS[user] = current
        _save_locked()
    _notify(user)


def add_bookmark(user: str, row: Dict[str, str]) -> None:
    tup = (row["left"], row["kw"], row["right"])
    with _LOCK:
        _load_locked()
        _BOOKMARKS.setdefault(user, set()).add(tup)
        _save_locked()
    _notify(user)


def remove_bookmark(user: str, row: Dict[str, str]) -> None:
    tup = (row["left"], row["kw"], row["right"])
    with _LOCK:
        _load_locked()
        if user in _BOOKMARKS:
            _BOOKMARKS[user].discard(tup)
        _save_locked()
    _notify(user)


def get_state(user: str) -> Dict[str, Any]:
    with _LOCK:
        _load_locked()
        return {
            "prefs": dict(_PREFS.get(user, {})),
            "bookmarks": [
                {
                    "left": t[0],
                    "kw": t[1],
                    "right": t[2],
                }
                for t in sorted(_BOOKMARKS.get(user, set()))
            ],
        }


async def subscribe(user: str) -> AsyncGenerator[Dict[str, Any], None]:
    q: asyncio.Queue[Dict[str, Any]] = register(user)
    try:
        while True:
            state = await q.get()
            yield state
    finally:
        unregister(user, q)
