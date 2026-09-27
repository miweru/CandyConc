"""Modules of this change compile without invalid escape sequences.

Python 3.12 turns an invalid escape in a string literal into a SyntaxWarning
(3.10: DeprecationWarning). ``recipe_runtime.py`` had one in a docstring
(``\\```` in ``_im_codeblock``).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "candyconc"


@pytest.mark.parametrize("relpath", [
    "candyconc_copilot/recipe_runtime.py",
    "candyconc_copilot/interpretation_synthesis.py",
    "candyconc_copilot/method_sheet.py",
    "candyconc_copilot/experiment_log.py",
    "candyconc_copilot/grounding_refs.py",
    "candyconc_copilot/id_scrub.py",
    "answer_language.py",
])
def test_module_compiles_without_escape_warnings(relpath):
    source = (_SRC / relpath).read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(source, relpath, "exec")
