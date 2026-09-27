"""Indexes without a lemmatizer match uppercase and lowercase lemma queries consistently.

Build a small blank:de fixture and check counts through REST and KWIC.
The fallback lemma is the lowercase token form."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("spacy", reason="spaCy fehlt")
pl = pytest.importorskip("polars")

import scripts.jobs.build_fast_index_from_parquet as build_mod  # noqa: E402
from candyconc.core.corpus_index import CorpusIndex  # noqa: E402
from candyconc.core.query_runtime import run_query  # noqa: E402

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def blank_index(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("blank_lemma")
    rows = {
        "source": ["news", "news"], "doc_id": ["d0", "d1"], "variant": ["original", "original"],
        "model": ["human", "human"], "text_type": ["human", "human"],
        "target_text": ["Die Regierung tagt. Die REGIERUNG beschliesst.",
                        "Eine regierung ohne Regierungen."],
    }
    eingabe = tmp / "blank.parquet"
    pl.DataFrame(rows).write_parquet(eingabe)
    ziel = tmp / "index"
    build_mod.build_fast_index_from_parquet(
        eingabe, ziel, spacy_model="blank:de", batch_size=2, n_process=1,
        disable_ner=True, disable_deps=True, split_long_texts=False, max_doc_chars=0,
        include_prompts=False, require_input_text=False,
        build_embeddings=False, build_gemma_embeddings=False,
    )
    idx = CorpusIndex(ziel)
    yield idx
    idx.close()


def _zeilen(idx, cql: str) -> int:
    return len(list(run_query("cql:" + cql, ctx=1, corpus=idx)))


def _zaehlung(idx, cql: str) -> int:
    from candyconc.services.backend.server import _compute_query_count

    gesamt, _ms, _teilweise = _compute_query_count(idx, cql, 0, None, None, None, case_insensitive=True)
    return int(gesamt)


@pytest.mark.parametrize("cql, erwartet", [
    ('[lemma="regierung"]', 3), ('[lemma="Regierung"]', 3), ('[lemma="REGIERUNG"]', 3),
    ('[lemma in {"Regierung","Die"}]', 5), ('[word="Regierung"]', 1), ('[lemma="Regierungen"]', 1),
])
def test_lemma_zaehlt_die_kleingeschriebene_wortform(blank_index, cql, erwartet):
    assert _zaehlung(blank_index, cql) == erwartet
    assert _zeilen(blank_index, cql) == erwartet


def test_ein_index_mit_lemmatisierer_bleibt_unberuehrt():
    if not _BENCH or not os.path.isdir(_BENCH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    from cqlhpc.predicates import lemma_ist_kleingeschriebene_wortform

    idx = CorpusIndex(_BENCH)
    try:
        assert _zaehlung(idx, '[lemma="und"]') == 916
        assert lemma_ist_kleingeschriebene_wortform(type("K", (), {"backend": idx.fast_index})()) is False
    finally:
        idx.close()
