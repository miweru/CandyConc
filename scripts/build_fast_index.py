#!/usr/bin/env python3
"""Fast Index writers shared by the builders (compatibility entry point).

The implementation is ``candyconc.ingest.build_fast_index``, which ships with the
``candyconc`` package. This file keeps ``python scripts/build_fast_index.py ...`` and
``import scripts.build_fast_index`` working: both use the packaged module. In a source checkout
the checkout's ``src`` directory comes first on ``sys.path``.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "app/src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.ingest import build_fast_index as _impl  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_impl.main())

# A regular import gets the packaged module object itself. Loaders that exec
# this file directly (importlib.util.spec_from_file_location) see its names.
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
sys.modules[__name__] = _impl
