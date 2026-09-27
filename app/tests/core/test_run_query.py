"""run_query KWIC contract on a real Fast Index.

CorpusIndex(":memory:") + import_tokens belongs to the retired SQLite era; the
Fast Index requires an on-disk directory (corpus_index.py: "Fast Index erwartet
ein Verzeichnis mit meta.bin"). Build one tiny REAL index with a blank spaCy
pipeline + fake annotator (pattern: tests/tools/conftest.py and
tests/core/test_build_index_roundtrip.py), then exercise the actual
query_runtime.run_query contract.

``build_tiny_fast_index`` / ``annotate_basic`` are shared by the other
search-cluster tests (test_run_query_multi, test_morph_search,
test_dependency_search, test_lineage, test_ranking_metric_persistence).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.query_runtime import run_query, set_corpus

REPO_ROOT = Path(__file__).resolve().parents[3]

TOKENS_TEXT = "the quick brown fox jumps over the lazy dog ."

BASIC_COMPONENT = "cc_core_basic_annot"


def annotate_basic(doc):
    # Blank pipelines emit lemma/pos == 0, which leaves those lexicons empty and
    # makes the index writer raise "Lexikon leer". Trivial non-zero annotations
    # keep the model-free fixture on the full lexicon/postings chain.
    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = "X"
    return doc


def build_tiny_fast_index(
    out_dir: Path,
    text: str,
    *,
    component: str = BASIC_COMPONENT,
    annotate=annotate_basic,
    enable_deps: bool = False,
) -> Path:
    """Build a tiny real on-disk Fast Index from ``text`` (one document).

    ``annotate`` is registered as a spaCy component named ``component`` and
    fully controls lemma/pos/morph (and dep/head when ``enable_deps``), so no
    downloaded model is needed.
    """
    import polars as pl
    import spacy
    from spacy.language import Language

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import scripts.jobs.build_fast_index_from_parquet as build_mod

    if component not in Language.factories:
        Language.component(component)(annotate)

    def _blank_load(_name, disable=None, **_kw):
        nlp = spacy.blank("en")
        # When dependency indexing is enabled the builder requires a pipe
        # literally named "parser" (_load_spacy_pipeline: "The spaCy pipeline
        # has no parser, but enable_deps is set.").
        nlp.add_pipe(component, name="parser" if enable_deps else component)
        return nlp

    inp = out_dir / "docs.parquet"
    pl.DataFrame({"id": ["d0"], "text": [text], "register": ["x"]}).write_parquet(inp)
    out = out_dir / "idx"
    real_load = spacy.load
    spacy.load = _blank_load
    try:
        build_mod.build_fast_index_generic(
            inp,
            out,
            spacy_model="blank_en",
            text_column="text",
            id_column="id",
            meta_columns=["register"],
            batch_size=1,
            n_process=1,
            disable_deps=not enable_deps,
        )
    finally:
        spacy.load = real_load
    return out


class TestRunQuery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_run_query_idx_")
        cls.index_path = build_tiny_fast_index(Path(cls._tmp), TOKENS_TEXT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)

    def tearDown(self):
        set_corpus(None)
        self.idx.close()

    def test_run_query_returns_rows(self):
        results = list(run_query("fox", ctx=2))
        self.assertGreaterEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["kw"], "fox")
        self.assertIn("brown", row["left"])
        self.assertIn("pos", row)

    def test_sample_contains_dog(self):
        rows = list(run_query("dog", ctx=2))
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["kw"], "dog")

    def test_no_duplicate_rows(self):
        rows = list(run_query("fox", ctx=1))
        self.assertEqual(len(rows), 1)

    def test_none_term_no_index(self):
        set_corpus(None)
        self.assertEqual(list(run_query(None)), [])
        set_corpus(self.idx)


if __name__ == "__main__":
    unittest.main()
