"""cqlhpc.autocomplete stays below candyconc in the import layering.

The where() suggestion needs the metadata fields that tell documents apart.
That rule lives in ``candyconc.core.meta_index.descriptive_fields``. The
autocompleter imported it lazily, which broke the import contract "cqlhpc ist
Leaf" (``lint-imports``) and made ``cqlhpc.autocomplete`` fail without
candyconc. The field selection is now handed in by the caller
(``where_fields``), and ``candyconc.core.cql_engine`` computes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

# Runs in a fresh interpreter in which every ``candyconc`` import fails.
_SCRIPT = textwrap.dedent(
    """
    import importlib.abc
    import json
    import sys
    from types import SimpleNamespace


    class BlockCandyconc(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "candyconc" or name.startswith("candyconc."):
                raise ModuleNotFoundError(f"blocked: {name}")
            return None


    sys.meta_path.insert(0, BlockCandyconc())

    from cqlhpc.autocomplete import complete


    class Field:
        def __init__(self, values):
            self._values = values

        def sample_str_values(self, max_scan=256):
            return list(self._values)


    meta_index = SimpleNamespace(
        fields={
            "author": Field([("Ann", 1), ("Ben", 1), ("Cy", 1)]),
            "genre": Field([("fiction", 1), ("news", 2)]),
        }
    )
    corpus = SimpleNamespace(backend=SimpleNamespace(meta_index=meta_index))

    def where_labels(**kwargs):
        return [s.label for s in complete("", 0, corpus, **kwargs) if s.label.startswith("where(")]

    print(json.dumps({
        "without_fields": where_labels(),
        "genre_first": where_labels(where_fields=["genre", "author"]),
        "no_string_values": where_labels(where_fields=["missing"]),
    }))
    """
)


def test_autocomplete_runs_without_candyconc_and_takes_the_field_selection():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC.parent),
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    # Without a field selection there is no field to filter by, so the
    # corpus-bound where() snippet is left out.
    assert result["without_fields"] == []
    # The first handed-in field with string values, and its most frequent value.
    assert result["genre_first"] == ['where(genre="news", $1)']
    # A field the metadata index does not know offers nothing.
    assert result["no_string_values"] == []
