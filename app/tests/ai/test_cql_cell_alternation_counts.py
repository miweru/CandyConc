"""Parenthesized cell alternation counts, and legacy pipe syntax suggests a working form."""

from __future__ import annotations

import os
import re

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.cql_macros import normalize_query_input
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


def _zahl(abfrage: str) -> int:
    return int(_TW.query_count_tool(abfrage)["total"])


def test_die_gruppe_ist_cql_und_die_altgruppe_bleibt_alt():
    assert normalize_query_input('([word="zudem"] | [word="außerdem"])').startswith("cql:")
    assert normalize_query_input("([pos=ADJ] OR cat) AND NOT ([lemma=go] NEAR/2 [pos=VERB])") == (
        "([pos=ADJ] OR cat) AND NOT ([lemma=go] NEAR/2 [pos=VERB])")


def test_die_geklammerte_alternation_zaehlt_wie_ihre_teile(index):
    einzeln = _zahl('[word="und"]') + _zahl('[word="oder"]')
    assert einzeln == 913
    assert _zahl('([word="und"] | [word="oder"])') == einzeln
    assert _zahl('([word="und"%c] | [word="oder"%c])') == _zahl('[word in {"und","oder"}%c]') == 1047


@pytest.mark.parametrize("abfrage, anfang", [("(und | oder)", "Expected )"), ("und | oder", "Unexpected token: |")])
def test_der_senkrechte_strich_im_altparser_nennt_die_zaehlenden_formen(index, abfrage, anfang):
    with pytest.raises(_TW.ToolInputError) as fehler:
        _TW.query_count_tool(abfrage)
    meldung = str(fehler.value)
    assert meldung.startswith(anfang), meldung
    formen = re.findall(r'\[word[^\]]*\](?: \| \[word[^\]]*\])?', meldung)
    assert len(formen) == 2, meldung
    # Genannt ist nur, was wirklich zaehlt: die Formen der Meldung, eingesetzt.
    for form in formen:
        eingesetzt = form.replace('"a"', '"und"').replace('"b"', '"oder"')
        assert _zahl(eingesetzt) == 913, eingesetzt
        assert _zahl(eingesetzt.replace('"]', '"%c]').replace('"}]', '"}%c]')) == 1047, eingesetzt


def test_die_wortsuche_mit_or_bleibt_wie_sie_war(index):
    assert _zahl("(und OR oder)") == 1047
