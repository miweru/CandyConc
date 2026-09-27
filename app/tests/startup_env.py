"""Environment values as the test run started, before test modules change them.

Several test modules set ``CANDYCONC_INDEX_PATH`` with ``os.environ.setdefault``
when they are imported. A module that reads the variable at import sees what
the modules collected before it wrote, so its outcome depends on the order.
``tests/conftest.py`` imports this module before any test module, and modules
that decide at import whether they have an index read :data:`INDEX_PATH`.

A path that does not exist counts as unset, as in
``conftest._drop_missing_index_env``.
"""

from __future__ import annotations

import os
from pathlib import Path


def _existing(raw: str | None) -> str | None:
    if raw and Path(raw).expanduser().exists():
        return raw
    return None


#: CANDYCONC_INDEX_PATH at the start of the run, None when unset or missing.
INDEX_PATH: str | None = _existing(os.environ.get("CANDYCONC_INDEX_PATH"))
