"""Morph/pos attribute search on a real Fast Index.

The retired SQLite-era ``CorpusIndex(path).import_text(...)`` API is gone.
The tiny index is built with a fake annotator that sets pos/morph directly,
so no ``en_core_web_sm`` download is needed.

Real morph contract: the index builder stores one morph tag per token as
``"<POS>|<MorphString>"`` (or just ``"<POS>"`` when the token has no morph;
see ``_map_morph_ids`` in scripts/jobs/build_fast_index_from_parquet.py), and
``[morph=...]`` resolves via an EXACT lexicon lookup
(FastIndexBackend.attr_positions -> term_positions(attr="morph")). The old
``[morph=Tense=Past]`` substring-style query therefore becomes
``[morph=VERB|Tense=Past]``.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.query_runtime import run_query, set_corpus

from tests.core.test_run_query import build_tiny_fast_index

MORPH_TEXT = "walked walks walking talk talked"

_POS = {
    "walked": "VERB",
    "walks": "VERB",
    "walking": "VERB",
    "talk": "NOUN",
    "talked": "VERB",
}
_MORPH = {
    "walked": "Tense=Past",
    "talked": "Tense=Past",
    "walking": "Aspect=Prog",
}


def annotate_morph(doc):
    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = _POS.get(tok.text, "X")
        morph = _MORPH.get(tok.text)
        if morph:
            tok.set_morph(morph)
    return doc


class TestMorphSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_morph_idx_")
        cls.index_path = build_tiny_fast_index(
            Path(cls._tmp),
            MORPH_TEXT,
            component="cc_core_morph_annot",
            annotate=annotate_morph,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.index = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.index)

    def tearDown(self):
        set_corpus(None)
        self.index.close()

    def test_past_tense_search(self):
        rows = list(run_query("[morph=VERB|Tense=Past]"))
        kws = {r["kw"] for r in rows}
        self.assertEqual(kws, {"walked", "talked"})

    def test_progressive_search(self):
        rows = list(run_query("[morph=VERB|Aspect=Prog]"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kw"], "walking")

    def test_pos_search(self):
        rows = list(run_query("[pos=VERB]"))
        kws = {r["kw"] for r in rows}
        self.assertEqual(kws, {"walked", "walks", "walking", "talked"})
        self.assertNotIn("talk", kws)


if __name__ == "__main__":
    unittest.main()
