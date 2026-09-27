"""Snapshot/restore guard for ``sys.modules`` around real-module loaders.

Several tests in this directory load the REAL copilot modules at import
(collection) time via ``spec_from_file_location`` and, while doing so,
install temporary stub packages under PRODUCTION names (``candyconc``,
``candyconc.services`` ...).  Without a restore, those stubs leak into the
process and break tests in OTHER directories (tests/backend monkeypatches
like ``candyconc.services.backend.kwic`` stop resolving).

``preserve_sys_modules`` snapshots the named entries before the loader runs
and restores them afterwards (re-inserting saved modules, popping entries
that did not exist before).

``relink_parent_attrs`` heals the attribute chain afterwards: when a real
submodule (e.g. ``candyconc.config``) is first imported WHILE a temporary
stub parent is installed, the import system sets the ``config`` attribute on
the stub parent only.  After the restore, the real parent package would lack
the attribute, breaking ``mock.patch``/``monkeypatch`` dotted-path lookup
(which walks ``getattr`` and does NOT re-set parent attributes for cached
modules).  Filling only MISSING attributes keeps deliberate shims (e.g. the
conftest tooling-registry stub) untouched.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator, Sequence


@contextmanager
def preserve_sys_modules(names: Sequence[str]) -> Iterator[None]:
    """Snapshot the given ``sys.modules`` entries, restore them on exit."""
    saved = {name: sys.modules.get(name) for name in names}
    had = {name: name in sys.modules for name in names}
    try:
        yield
    finally:
        for name in names:
            if had[name]:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)
        relink_parent_attrs()


def relink_parent_attrs(prefix: str = "candyconc") -> None:
    """Set missing parent-package attributes for cached submodules."""
    for name, module in list(sys.modules.items()):
        if module is None or "." not in name or not name.startswith(prefix):
            continue
        parent_name, _, child = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and not hasattr(parent, child):
            try:
                setattr(parent, child, module)
            except Exception:  # pragma: no cover - exotic module objects
                pass
