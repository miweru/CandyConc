"""Word search reports unsupported alternation or attribute syntax as input errors."""

from __future__ import annotations

import os
import re

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
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


def _meldungen(abfrage: str) -> list[str]:
    meldungen = []
    for aufruf in (lambda: _TW.query_count_tool(abfrage),
                   lambda: _TW.run_cqlf_query_tool(abfrage, limit=1, sort_by="position")):
        with pytest.raises(_TW.ToolInputError) as fehler:
            aufruf()
        meldungen.append(str(fehler.value))
    return meldungen


@pytest.mark.parametrize("abfrage", ["(und|oder)", "und|oder"])
def test_oder_mit_senkrechtem_strich_nennt_die_zaehlenden_formen(index, abfrage):
    for meldung in _meldungen(abfrage):
        formen = re.findall(r'und OR oder|\[word="und"\] \| \[word="oder"\]|\[word in \{"und","oder"\}\]', meldung)
        assert len(set(formen)) == 3, meldung
        assert _TW.query_count_tool("und OR oder")["total"] == 1047
        assert _TW.query_count_tool('[word="und"%c] | [word="oder"%c]')["total"] == 1047
        assert _TW.query_count_tool('[word in {"und","oder"}%c]')["total"] == 1047


@pytest.mark.parametrize("abfrage, form, erwartet", [
    ("word=und", '[word="und"]', 797), ('word="und"', '[word="und"]', 797),
    ("lemma=und", '[lemma="und"]', 916), ('lemma="und"', '[lemma="und"]', 916),
    ("pos=NOUN", '[pos="NOUN"]', 9740),
])
def test_attributschreibweise_ohne_klammern_nennt_die_form_in_klammern(index, abfrage, form, erwartet):
    for meldung in _meldungen(abfrage):
        assert form in meldung, meldung
    assert _TW.query_count_tool(form)["total"] == erwartet


@pytest.mark.parametrize("abfrage, erwartet", [("Evangelisch|er", 1), ("und", 919), ("Notfall", 0)])
def test_was_vorkommt_oder_ein_gewoehnliches_wort_ist_bleibt_eine_zahl(index, abfrage, erwartet):
    assert _TW.query_count_tool(abfrage)["total"] == erwartet
    assert _TW.run_cqlf_query_tool(abfrage, limit=1, sort_by="position")["total"] == erwartet
