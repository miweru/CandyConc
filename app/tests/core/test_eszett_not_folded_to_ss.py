"""Case-insensitive matching preserves the distinction between sharp s and ss."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from candyconc.domain.query_parser import casefold_key
from cqlhpc.predicates import _casefold_match_ids

_INDEX = os.environ.get("CANDYCONC_INDEX_PATH")

_echter_index = pytest.mark.skipif(
    not _INDEX or not Path(_INDEX).is_dir(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


# --------------------------------------------------------------------------- #
# Kleinste Einheit: der Schluessel und der CQL-%c-Vergleich
# --------------------------------------------------------------------------- #


def test_der_schluessel_trennt_eszett_und_ss() -> None:
    assert casefold_key("daß") != casefold_key("dass")
    assert casefold_key("Straße") != casefold_key("Strasse")
    assert casefold_key("Maße") != casefold_key("Masse")


def test_der_schluessel_faltet_die_grossschreibung_weiter() -> None:
    assert casefold_key("DASS") == casefold_key("Dass") == casefold_key("dass")
    assert casefold_key("STRASSE") == casefold_key("Strasse")
    # Das grosse Eszett ist die Grossschreibung von ß, nicht von ss.
    assert casefold_key("STRAẞE") == casefold_key("Straße") == "straße"


class _Lexikon:
    """Ein Lexikon, wie ``_iter_lexicon_ids`` und ``_lex_string_for_id`` es lesen."""

    def __init__(self, formen: list[str]) -> None:
        self.id_to_str = ["", *formen]


_FORMEN = ["daß", "dass", "Dass", "DASS", "Straße", "Strasse", "STRAẞE", "STRASSE"]


def _formen_fuer(ziel: str) -> set[str]:
    lex = _Lexikon(_FORMEN)
    return {lex.id_to_str[int(i)] for i in _casefold_match_ids(lex, [ziel])}


def test_cql_prozent_c_trennt_eszett_und_ss() -> None:
    assert _formen_fuer("daß") == {"daß"}
    assert _formen_fuer("dass") == {"dass", "Dass", "DASS"}
    assert _formen_fuer("DASS") == {"dass", "Dass", "DASS"}
    assert _formen_fuer("Straße") == {"Straße", "STRAẞE"}
    assert _formen_fuer("strasse") == {"Strasse", "STRASSE"}


# Check each counting boundary against the reference index.


@pytest.fixture(scope="module")
def index():
    from candyconc.core.corpus_index import CorpusIndex

    idx = CorpusIndex(Path(_INDEX), read_only=True)
    yield idx
    idx.close()


def _genau(index, form: str) -> int:
    return int(index.term_positions(form, case_insensitive=False).size)


@_echter_index
def test_der_bench_index_traegt_die_formen(index) -> None:
    """Ohne diese Formen waere jede folgende Probe leer und bestuende grundlos."""
    assert (_genau(index, "dass"), _genau(index, "Dass"), _genau(index, "daß")) == (179, 5, 7)
    assert (_genau(index, "Maße"), _genau(index, "Masse")) == (2, 1)


@_echter_index
def test_klartextsuche_zaehlt_daß_ohne_dass(index) -> None:
    daß = index.term_positions("daß", case_insensitive=True)
    assert int(daß.size) == 7
    dass = index.term_positions("dass", case_insensitive=True)
    assert int(dass.size) == 179 + 5
    assert not set(daß.tolist()) & set(dass.tolist())
    for gross in ("DASS", "Dass"):
        np.testing.assert_array_equal(
            np.sort(index.term_positions(gross, case_insensitive=True)), np.sort(dass)
        )
    assert int(index.term_positions("Maße", case_insensitive=True).size) == 2
    assert int(index.term_positions("Masse", case_insensitive=True).size) == 1


@_echter_index
def test_wildcard_und_regex_trennen_eszett_und_ss(index) -> None:
    # Vorher 193: das Muster wurde zu "dass.*" und traf dass, Dass, dasselbe,
    # Dasselbe und daß.
    assert int(index.wildcard_positions("daß*", case_insensitive=True).size) == 7
    ss = index.wildcard_positions("DASS*", case_insensitive=True)
    assert int(ss.size) == 179 + 5 + 1 + 1  # dass, Dass, dasselbe, Dasselbe
    assert not set(ss.tolist()) & set(index.term_positions("daß", case_insensitive=False).tolist())
    assert int(index.regex_positions("da(ß)", case_insensitive=True).size) == 7


@_echter_index
def test_phrase_trennt_eszett_und_ss(index) -> None:
    """„daß es“ steht zweimal im Testindex, „dass es“ sechzehnmal."""
    alt = set(index.sequence_positions(["daß", "es"], case_insensitive=True))
    assert alt == set(index.sequence_positions(["daß", "es"], case_insensitive=False))
    assert len(alt) == 2
    neu = set(index.sequence_positions(["DASS", "ES"], case_insensitive=True))
    assert len(neu) >= 16
    assert not alt & neu


@_echter_index
def test_cql_prozent_c_am_index() -> None:
    from candyconc.core import cql_engine
    from candyconc.core.fast_index_backend import FastIndexBackend

    backend = FastIndexBackend(Path(_INDEX))
    zaehle = lambda q: int(cql_engine.count_cql_matches_backend(backend, q))  # noqa: E731
    assert zaehle('cql:[word="daß"%c]') == 7
    assert zaehle('cql:[word="dass"%c]') == 184
    assert zaehle('cql:[word="DASS"%c]') == 184
    assert zaehle('cql:[word in {"daß","Maße"}%c]') == 7 + 2


@_echter_index
def test_kollokationsknoten_trennt_eszett_und_ss(index) -> None:
    from candyconc.core.collocation_engine import get_engine

    eng = get_engine(Path(_INDEX))
    assert int(eng._get_term_positions("daß", case_insensitive=True).size) == 7
    assert int(eng._get_term_positions("DASS", case_insensitive=True).size) == 184


@_echter_index
def test_gefaltete_frequenzliste_haelt_daß_und_dass_getrennt(index) -> None:
    fl = index.frequency_list(case_fold=True)
    zeilen = {str(w): int(f) for w, f in zip(fl["word"], fl["f"]) if str(w).lower() in {"daß", "dass"}}
    assert sorted(zeilen.values()) == [7, 184], zeilen
    assert sum(int(f) for w, f in zip(fl["word"], fl["f"]) if str(w).lower() == "maße") == 2


# --------------------------------------------------------------------------- #
# Werkzeugebene: REST und Copilot zaehlen dasselbe
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def werkzeuge(index):
    from candyconc.core import query_runtime as qr
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    vorher = getattr(qr, "_CORPUS_INDEX", None)
    qr._CORPUS_INDEX = index
    try:
        yield _load_real_tool_wrappers()
    finally:
        qr._CORPUS_INDEX = vorher


@_echter_index
@pytest.mark.parametrize(
    ("anfrage", "erwartet"),
    [("daß", 7), ("dass", 184), ("DASS", 184), ("Dass", 184), ("Maße", 2)],
)
def test_query_count_rest_und_copilot(index, werkzeuge, anfrage, erwartet) -> None:
    from candyconc.services.backend.server import _compute_query_count

    rest, _ms, teilweise = _compute_query_count(
        index, anfrage, 0, None, None, None, case_insensitive=True
    )
    copilot = werkzeuge.query_count_tool(anfrage, case_insensitive=True)
    assert copilot["status"] == "success"
    assert int(rest) == int(copilot["total"]) == erwartet
    assert not teilweise


@_echter_index
def test_schreibung_gefaltet_nennt_nur_die_grossschreibung(werkzeuge) -> None:
    dass = werkzeuge.query_count_tool("dass", case_insensitive=True)
    assert dass.get("schreibung_gefaltet") == {"dass": 179, "Dass": 5}
    daß = werkzeuge.query_count_tool("daß", case_insensitive=True)
    assert "schreibung_gefaltet" not in daß, daß.get("schreibung_gefaltet")


def test_kollokationsvergleich_behaelt_daß_und_dass_als_zwei_terme() -> None:
    """Die Terme eines Vergleichs werden mit demselben Vergleich entdoppelt wie
    die Zaehlung. Mit casefold fiel "dass" als Dublette von "daß" weg, und der
    Vergleich wurde gar nicht erkannt (leere Liste)."""
    from candyconc.candyconc_copilot.grounding_contracts import (
        same_corpus_collocation_terms,
    )

    frage = 'Vergleiche die Kollokate von "daß" und "dass" im Korpus.'
    assert same_corpus_collocation_terms(frage) == ["daß", "dass"]
    frage = 'Vergleiche die Kollokate von "Dass" und "dass" und "Maße".'
    assert same_corpus_collocation_terms(frage) == ["Dass", "Maße"]
