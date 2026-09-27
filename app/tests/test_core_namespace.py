import importlib
import pytest


def test_import_candyconc_core_modules():
    import candyconc.core.corpus_index as ci
    import candyconc.core.query_runtime as fp
    assert ci is not None and fp is not None


def test_no_core_package():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("core")
