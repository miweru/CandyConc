"""Eine reine Korpuszählung einer Regex-Zelle lehnt nicht mehr ab.

Kandidat 4 und Muse, Frage 11: [word=".{13,}"] endete mit „Regex Treffer zu
gross … 8.343.253 Tokens“, obwohl die Absage die Zahl kannte. Am Testindex
liegen die Muster unter der Grenze. Die Probe senkt die Grenze deshalb und
verlangt dieselbe Zahl wie der gewöhnliche Weg.
"""

import pytest

from candyconc.services.backend import regex_type_count


def test_einzelzelle_erkennt_nur_eine_zelle_ohne_flag():
    assert regex_type_count.einzelzelle('[word=".{13,}"]') == ("word", ".{13,}")
    assert regex_type_count.einzelzelle('cql:[lemma="geh.*"]') == ("lemma", "geh.*")
    assert regex_type_count.einzelzelle('[word=".{13,}"%c]') is None
    assert regex_type_count.einzelzelle('[word="a.*"] [word="b"]') is None


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


def test_die_absage_des_markerpfads_wird_zur_zaehlung(tw, monkeypatch):
    """Am Testindex (Marker |LBR| mit ID 134247) warf der Markerpfad
    exact_cql_count_sentinel_dropped fuer [word=".{13,}"] die Absage, mit der
    Reparatur zaehlt er 8.343.253 in 0,9 s, unter der Grenze gleich dem alten
    Weg (.{40,} 9.742, .{30,} 36.326). Der Testindex hat keinen Marker, die
    Probe baut den Pfad nach: Marker ist die ID von "und", die das Muster nicht
    trifft, und der Markerpfad wirft die Absage aus dem PING-Lauf."""
    from candyconc.core import query_runtime as qrt
    from candyconc.services.backend import server as _server

    abfrage = '[word=".{13,}"]'
    gewoehnlich = tw.query_count_tool(abfrage)["total"]
    und = int(qrt._CORPUS_INDEX.fast_index.lexicons.word.get_id("und"))

    def _absage(*_a, **_k):
        raise RuntimeError(
            "Regex Treffer zu gross fuer '.{13,}': 8.343.253 Tokens gegen eine Grenze "
            "von 5.000.000 (1,7-fach). Bitte Suchmuster einschraenken."
        )

    monkeypatch.setattr(_server, "_linebreak_sentinel_word_id", lambda _idx: und)
    monkeypatch.setattr(_server, "_exact_cql_count_sentinel_dropped", _absage)
    assert tw.query_count_tool(abfrage)["total"] == gewoehnlich


def test_zaehlpfad_gleich_dem_gewoehnlichen_weg(tw):
    from candyconc.core import query_runtime as qrt
    from candyconc.services.backend import regex_type_count, server as _server

    for muster in (".{13,}", "[a-zäöüß]+ung", ".*"):
        abfrage = '[word="' + muster + '"]'
        assert regex_type_count.zaehlen(
            qrt._CORPUS_INDEX, abfrage, _server._linebreak_sentinel_word_id
        ) == tw.query_count_tool(abfrage)["total"], muster
