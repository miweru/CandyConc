"""tests/core conftest: keep the full-directory run from aborting on macOS.

Duplicate-OpenMP gotcha: ``candyconc.core._fast_count`` links Homebrew
``libomp.dylib`` while torch (pulled in transitively by ``import spacy`` in
e.g. ``test_index_manifest.py``) ships its own copy. When ``_fast_count`` is
imported BEFORE spacy/torch in the same process — which is exactly what
happens in a full ``pytest tests/core`` run (the root conftest pulls in
candyconc first, ``test_collocation_engine_robustness.py`` then runs a dense
counting kernel after ``test_index_manifest.py`` imported spacy) — the second
libomp runtime aborts the process (SIGABRT) at the first OpenMP parallel
region in ``count_segments_svb_dense``.

``KMP_DUPLICATE_LIB_OK=TRUE`` is the documented libomp escape hatch for test
environments with two runtimes in one process. It must be in the environment
before torch's libomp initialises, so it is set at conftest import time
(conftest loads before any tests/core test module is imported).

Repro of the abort without this guard:
    pytest tests/core/test_index_manifest.py \
           tests/core/test_collocation_engine_robustness.py
"""

from __future__ import annotations

import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
