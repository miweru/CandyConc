"""QW1 (spacy-decouple): the build engine and its pure helpers must import and
run without spaCy installed.

After lazy-importing spaCy inside the three functions that actually load a model
(_preflight_checks, _load_spacy_pipeline, build_index_from_token_docs), the module
build_fast_index_from_parquet and model_registry are importable spaCy-free, and the
pure helpers (PairSink, BuildContext, _build_doc_stream, _text_hash, ...) are usable.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.jobs.build_fast_index_from_parquet import (  # noqa: E402
    PairSink,
    BuildContext,
    _build_doc_stream,
    _build_generic_doc_stream,
    _text_hash,
    _origin_id,
    _safe_str,
    _safe_meta_dict,
)
from candyconc import model_registry  # noqa: E402


def test_module_imports_without_calling_spacy():
    # The import above already proves the module loads with no module-level spaCy.
    assert callable(_build_doc_stream)
    assert callable(_build_generic_doc_stream)


def test_pairsink_cycle():
    s = PairSink()
    h = s.assign("h")
    a = s.assign("a")
    s.bind("h", h)
    s.bind("a", a)
    s.on_pair("h", "a")
    assert list(s.resolve_pairs()) == [(h, a)]


def test_build_context_defaults():
    ctx = BuildContext()
    assert ctx.phases == []
    assert ctx.warnings == []


def test_text_hash_stable():
    h = _text_hash("Hallo Welt")
    assert isinstance(h, str)
    assert _text_hash("Hallo Welt") == h


def test_origin_id_and_safe_helpers():
    assert _origin_id("news", "d1", None)
    assert _safe_str(None) is None
    assert _safe_meta_dict(None) == {}


def test_model_registry_importable_without_spacy():
    assert callable(model_registry.get_spacy)
    assert callable(model_registry.clear_registry)


def test_build_module_does_not_import_spacy_at_module_load():
    # Stronger proof than a plain import (which can't catch a re-added module-level
    # `import spacy` when spaCy is installed): block spaCy via a meta_path finder,
    # drop it from sys.modules, then re-import the build module fresh and assert it
    # loads. Restores spaCy afterwards so the rest of the suite is unaffected.
    import importlib

    class _BlockSpacy:
        def find_spec(self, name, path=None, target=None):
            if name == "spacy" or name.startswith("spacy."):
                raise ImportError(f"spaCy blocked for test: {name}")
            return None

    saved = {k: v for k, v in sys.modules.items() if k == "spacy" or k.startswith("spacy.")}
    saved_mod = sys.modules.get("scripts.jobs.build_fast_index_from_parquet")
    finder = _BlockSpacy()
    try:
        for k in list(saved):
            del sys.modules[k]
        sys.modules.pop("scripts.jobs.build_fast_index_from_parquet", None)
        sys.meta_path.insert(0, finder)
        mod = importlib.import_module("scripts.jobs.build_fast_index_from_parquet")
        assert hasattr(mod, "build_index_from_token_docs")
        assert "spacy" not in sys.modules  # truly never imported at module load
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
        sys.modules.update(saved)
        if saved_mod is not None:
            sys.modules["scripts.jobs.build_fast_index_from_parquet"] = saved_mod
