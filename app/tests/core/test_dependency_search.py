"""Dependency search on a real Fast Index with real dep/head postings.

The retired SQLite-era ``CorpusIndex(path).import_text(...)`` API is gone. The
tiny index is built with dependency indexing enabled (``disable_deps=False``)
and a fake "parser" component that sets pos/dep/head directly, so no
``en_core_web_sm`` download is needed.

Real contracts exercised here:
- ``[pos=VERB] >nsubj [pos=NOUN]`` -> Dependency node -> CorpusIndex
  .query_dependency with exact attribute-key semantics. The parser must preserve
  ``Attr.key``; a POS filter must not silently become a morph substring filter.
- ``[rel=nsubj]`` -> FastIndexBackend.rel_positions (exact rel lexicon lookup;
  rel ids live on the DEPENDENT token).
- Arcs: run_query only attaches arcs when CANDYCONC_ENABLE_KWIC_ARCS=1
  (query_eval._INCLUDE_ARCS, read at import time); the arc-bearing contract is
  CorpusIndex.query -> FastIndexBackend.kwic_rows(include_arcs=True). Arc
  tuples are window-relative ``(dep, head, rel)`` per
  ``dependency_arcs_window`` in core/_fast_index.pyx.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.query_runtime import run_query, set_corpus
from candyconc.domain.query_eval import prefetch_positions
from candyconc.domain.query_parser import Attr, Dependency, Term, parse_query

from tests.core.test_run_query import build_tiny_fast_index

DEP_TEXT = "cats jumped dogs barked"

_POS = {"cats": "NOUN", "dogs": "NOUN", "jumped": "VERB", "barked": "VERB"}


def annotate_deps(doc):
    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = _POS.get(tok.text, "X")
    # Two clauses: cats -nsubj-> jumped, dogs -nsubj-> barked.
    doc[0].head = doc[1]
    doc[0].dep_ = "nsubj"
    doc[1].head = doc[1]
    doc[1].dep_ = "ROOT"
    doc[2].head = doc[3]
    doc[2].dep_ = "nsubj"
    doc[3].head = doc[3]
    doc[3].dep_ = "ROOT"
    return doc


class TestDependencySearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_dep_idx_")
        cls.index_path = build_tiny_fast_index(
            Path(cls._tmp),
            DEP_TEXT,
            component="cc_core_dep_annot",
            annotate=annotate_deps,
            enable_deps=True,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)

    def tearDown(self):
        set_corpus(None)
        self.idx.close()

    def test_subject_verb_pairs(self):
        rows = list(run_query("[pos=VERB] >nsubj [pos=NOUN]", ctx=0))
        pairs = {(r["kw"], r["dep"]) for r in rows}
        self.assertEqual(pairs, {("jumped", "cats"), ("barked", "dogs")})

    def test_dependency_attribute_filter_preserves_attr_key(self):
        rows = list(run_query("[pos=VERB] >nsubj [lemma=dogs]", ctx=0))
        pairs = {(r["kw"], r["dep"]) for r in rows}
        self.assertEqual(pairs, {("barked", "dogs")})

    def test_relation_filter(self):
        rows = list(run_query("[rel=nsubj]", ctx=0))
        kws = {r["kw"] for r in rows}
        self.assertEqual(kws, {"cats", "dogs"})

    def test_side_without_match_counts_nothing(self):
        # A side that matches no token keeps its condition. Before, an empty
        # side was passed on as "no restriction", and the count found every
        # verb with any subject (sotu_en: freedom >amod xyzzyq counted 59).
        query = "[pos=VERB] >nsubj [lemma=nowhere]"
        self.assertEqual(prefetch_positions(query, self.idx).size, 0)
        self.assertEqual(list(run_query(query, ctx=0)), [])
        self.assertEqual(prefetch_positions("[lemma=nowhere] >nsubj [pos=NOUN]", self.idx).size, 0)

    def test_kwic_arcs(self):
        # CorpusIndex.query is the arc-bearing KWIC path (include_arcs=True by
        # default in FastIndexBackend.kwic_rows). "jumped" sits at token 1 with
        # ctx=1, so the window starts at token 0 and the cats->jumped nsubj arc
        # is window-relative (0, 1, "nsubj").
        row = next(self.idx.query("jumped", ctx=1))
        self.assertIn((0, 1, "nsubj"), row.get("arcs", []))


KEYWORD_TEXT = "cats sat near walls dogs ran within gates"

_KEYWORD_POS = {
    "cats": "NOUN", "walls": "NOUN", "dogs": "NOUN", "gates": "NOUN",
    "sat": "VERB", "ran": "VERB", "near": "ADP", "within": "ADP",
}


def annotate_keyword_deps(doc):
    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = _KEYWORD_POS.get(tok.text, "X")
    # cats -nsubj-> sat, near -prep-> sat, walls -pobj-> near,
    # dogs -nsubj-> ran, within -prep-> ran, gates -pobj-> within.
    arcs = [(0, 1, "nsubj"), (1, 1, "ROOT"), (2, 1, "prep"), (3, 2, "pobj"),
            (4, 5, "nsubj"), (5, 5, "ROOT"), (6, 5, "prep"), (7, 6, "pobj")]
    for dep, head, rel in arcs:
        doc[dep].head = doc[head]
        doc[dep].dep_ = rel
    return doc


class TestDependencyKeywordWords(unittest.TestCase):
    """The words "within" and "where" inside a dependency query are words.

    Before, the term canonicalization read them as the CQL keywords and turned
    them into "cql:within", which matched nothing, and the empty side dropped
    its condition: sotu_en "[word=is] >prep [word=within]" counted 540, the
    word sketch row has 7 pairs.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_dep_kw_idx_")
        cls.index_path = build_tiny_fast_index(
            Path(cls._tmp),
            KEYWORD_TEXT,
            component="cc_core_dep_keyword",
            annotate=annotate_keyword_deps,
            enable_deps=True,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)

    def tearDown(self):
        set_corpus(None)
        self.idx.close()

    def test_keyword_values_stay_words(self):
        node = parse_query("[word=ran] >prep [word=within]")
        self.assertEqual(node, Dependency(Attr("word", "ran"), Attr("word", "within"), "prep"))
        self.assertEqual(parse_query("ran >prep Where").dep, Term("Where"))

    def test_keyword_collocate_counts_its_pairs(self):
        self.assertEqual(prefetch_positions("[word=ran] >prep [word=within]", self.idx).size, 1)
        self.assertEqual(prefetch_positions("[word=sat] >prep [word=within]", self.idx).size, 0)
        self.assertEqual(prefetch_positions("[pos=VERB] >prep [word=within]", self.idx).size, 1)
        self.assertEqual(prefetch_positions("[word=within] >pobj [word=gates]", self.idx).size, 1)
        self.assertEqual(prefetch_positions("ran >prep within", self.idx).size, 1)


if __name__ == "__main__":
    unittest.main()
