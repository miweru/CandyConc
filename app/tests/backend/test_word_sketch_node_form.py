"""The word sketch names the node form it counts (back path to the KWIC).

The sketch counts the exact form when the lexicon has it, else the lower case
form. The response carries that form as ``node``, and the dependency query
built from node, relation and collocate counts the pairs of the row.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.services.backend import server as srv
from candyconc.services.backend.routes import analysis as analysis_routes

from tests.core.test_run_query import build_tiny_fast_index

TEXT = "cats chase dogs dogs chase cats Dogs chase cats"
_POS = {"cats": "NOUN", "dogs": "NOUN", "Dogs": "NOUN", "chase": "VERB"}
_ARCS = [(0, 1, "nsubj"), (1, 1, "ROOT"), (2, 1, "dobj"),
         (3, 4, "nsubj"), (4, 4, "ROOT"), (5, 4, "dobj"),
         (6, 7, "nsubj"), (7, 7, "ROOT"), (8, 7, "dobj")]


def annotate(doc):
    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = _POS.get(tok.text, "X")
    for dep, head, rel in _ARCS:
        doc[dep].head = doc[head]
        doc[dep].dep_ = rel
    return doc


class TestWordSketchNodeForm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_ws_node_")
        cls.index_path = build_tiny_fast_index(
            Path(cls._tmp), TEXT, component="cc_ws_node_annot", annotate=annotate, enable_deps=True
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        self._get_corpus = srv.get_corpus
        srv.get_corpus = lambda corpus=None: self.idx

    def tearDown(self):
        srv.get_corpus = self._get_corpus
        self.idx.close()

    def sketch(self, term):
        return asyncio.run(analysis_routes.word_sketch_endpoint(payload={"term": term, "min_freq": 0}))

    def test_node_is_the_form_the_sketch_counts(self):
        self.assertEqual(self.sketch("chase")["node"], "chase")
        self.assertEqual(self.sketch("Dogs")["node"], "Dogs")
        self.assertEqual(self.sketch("DOGS")["node"], "dogs")
        self.assertEqual(self.sketch("CHASE")["node"], "chase")
        self.assertIsNone(self.sketch('cql:[lemma="chase"]')["node"])

    def test_dependency_query_of_a_row_counts_its_pairs(self):
        res = self.sketch("chase")
        node = res["node"]
        rows = {(rel, row["word"]): row["f"] for rel, table in res["sketches"].items() for row in table}
        self.assertEqual(rows[("dobj", "cats")], 2)
        for (relation, collocate), pairs in rows.items():
            query = f"[word={node}] >{relation} [word={collocate}]"
            count = srv._compute_query_count(self.idx, query, 5, None, None)[0]
            self.assertEqual(count, pairs, query)
        # The collocate keeps its spelling: Dogs and dogs are two rows.
        self.assertEqual(rows[("nsubj", "Dogs")], 1)
        self.assertEqual(rows[("nsubj", "dogs")], 1)
        # A typed form missing from the lexicon falls back to lower case.
        self.assertEqual(self.sketch("CHASE")["sketches"], res["sketches"])

    def test_sketch_difference_names_both_nodes(self):
        res = asyncio.run(analysis_routes.analysis_wordsketch_diff(
            payload={"term_a": "chase", "term_b": "DOGS", "min_freq": 0}
        ))
        self.assertEqual((res["node_a"], res["node_b"]), ("chase", "dogs"))


if __name__ == "__main__":
    unittest.main()
