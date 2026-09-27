"""A CQL count without %c reports the occurrences excluded by case sensitivity."""

import pytest

from candyconc.candyconc_copilot import grounding_evidence as ge
from candyconc.candyconc_copilot.case_variant_count import mit_c


def test_mit_c_setzt_das_flag_an_jeder_zelle_ohne_flag():
    assert mit_c('[word="darüber"] [word="hinaus"]') == '[word="darüber"%c] [word="hinaus"%c]'
    assert mit_c('cql:[lemma="gehen"]') == 'cql:[lemma="gehen"%c]'
    assert mit_c('[word="darüber"%c] [word="hinaus"%c]') is None
    assert mit_c("darüber hinaus") is None
    assert mit_c('[word="x" & pos="NOUN"]') is None


@pytest.fixture(scope="module")
def tw():
    import os

    from candyconc.core import query_runtime as qrt
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.services.backend import server as _server
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    pfad = os.environ.get("CANDYCONC_INDEX_PATH")
    if not pfad or not os.path.isdir(pfad):
        pytest.skip("CANDYCONC_INDEX_PATH zeigt nicht auf einen Index")
    idx = CorpusIndex(pfad)
    vorher_qrt, vorher_server = qrt._CORPUS_INDEX, getattr(_server, "_INDEX", None)
    qrt._CORPUS_INDEX = idx
    _server.set_default_index(idx)
    try:
        yield _load_real_tool_wrappers()
    finally:
        qrt._CORPUS_INDEX = vorher_qrt
        _server.set_default_index(vorher_server)


def test_cql_ohne_c_meldet_die_zahl_mit_c(tw):
    exakt = tw.query_count_tool('[word="und"]')
    gefaltet = tw.query_count_tool('[word="und"%c]')
    assert exakt["total"] == 797 and gefaltet["total"] > exakt["total"]
    assert exakt["mit_c"]["total"] == gefaltet["total"]
    assert "mit_c" not in gefaltet


def test_mit_c_erreicht_die_belegzeilen(tw):
    ausgabe = tw.query_count_tool('[word="und"]')
    zeilen = ge.build_grounding_surface(ge.extract_raw_surface(ausgabe, werkzeug="query_count"))
    assert any("mit_c" in z and str(ausgabe["mit_c"]["total"]) in z for z in zeilen), zeilen
