"""Shared scaffold for tests/tools.

CorpusIndex(":memory:") + import_tokens belongs to the retired SQLite era;
the Fast Index requires an on-disk directory (corpus_index.py: "Fast Index
erwartet ein Verzeichnis mit meta.bin"). Build one tiny real index per test
session, same pattern as tests/core/test_build_index_roundtrip.py.
"""

from pathlib import Path

import pytest

TOKENS_TEXT = "the quick brown fox jumps over the lazy dog ."

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def tools_tiny_index_path(tmp_path_factory) -> Path:
    spacy = pytest.importorskip("spacy", reason="spaCy required to build the tiny index")
    pytest.importorskip("polars", reason="polars required to build the tiny index")
    import sys

    import polars as pl
    from spacy.language import Language

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import scripts.jobs.build_fast_index_from_parquet as build_mod

    if "tools_fake_annot" not in Language.factories:
        @Language.component("tools_fake_annot")
        def _tools_fake_annot(doc):
            for tok in doc:
                tok.lemma_ = tok.lower_
                tok.pos_ = "X"
            return doc

    def _blank_load(_name, disable=None, **_kw):
        nlp = spacy.blank("de")
        nlp.add_pipe("tools_fake_annot")
        return nlp

    tmp = tmp_path_factory.mktemp("tools_tiny_idx")
    inp = tmp / "docs.parquet"
    pl.DataFrame(
        {
            "id": ["d0"],
            "text": [TOKENS_TEXT],
            "register": ["x"],
        }
    ).write_parquet(inp)
    out = tmp / "idx"
    real_load = spacy.load
    spacy.load = _blank_load
    try:
        build_mod.build_fast_index_generic(
            inp, out, spacy_model="de_blank", text_column="text",
            id_column="id", meta_columns=["register"], batch_size=1, n_process=1,
        )
    finally:
        spacy.load = real_load
    return out


@pytest.fixture()
def tokens_corpus(tools_tiny_index_path):
    """Open the tiny index and install it as the active runtime corpus."""
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core.query_runtime import set_corpus

    idx = CorpusIndex(tools_tiny_index_path, read_only=True)
    set_corpus(idx)
    try:
        yield idx
    finally:
        set_corpus(None)
        idx.close()
