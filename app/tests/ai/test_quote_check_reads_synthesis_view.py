"""Quote checks use the hit rows and search terms visible to synthesis."""

import json

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_TREFFER = {
    "id": "E_run_cqlf_query_23", "tool": "run_cqlf_query",
    "query": json.dumps({"query": '[word="zudem" %c] []{1,25} [word="außerdem" %c]'}),
    "grounding_surface": [
        'match[0]="zudem schwere Vorwürfe : Es seien Stimmen gekauft worden , außerdem"',
        'kwic[0] "Die Opposition erhebt zudem schwere Vorwürfe : Es seien"',
    ],
    "fact_surface": {"rows": [{"kw": "zudem", "left": "Die Opposition erhebt",
                               "match": "zudem schwere Vorwürfe : Es seien Stimmen gekauft worden , außerdem",
                               "right": "schwere Vorwürfe : Es seien", "file": "gpt-5.2:doc", "pos": 5}], "total": 3},
}
_ZAEHLUNG = {"id": "E_query_count_28", "tool": "query_count",
             "query": json.dumps({"query": '[word="darüber" %c] [word="hinaus" %c]'}),
             "grounding_surface": ["total=751", "per_million=26.0"]}
_KWIC = {"id": "E_run_cqlf_query_17", "tool": "run_cqlf_query", "query": json.dumps({"query": "gleichzeitig"}),
         "grounding_surface": ['kwic[0] "und sich gleichzeitig die Plausibilität bewahrt"',
                               'kwic[1] "schwäche zugleich das Vertrauen in die digitale"']}


def test_ein_echter_mehrwort_treffer_ist_belegt():
    text = ("„Die Opposition erhebt zudem schwere Vorwürfe: Es seien Stimmen gekauft worden, außerdem“ "
            "[[beleg:E_run_cqlf_query_23]].")
    assert modul._unverifizierte_zitate(text, [_TREFFER]) == []


def test_begriffsnennungen_sind_belegt():
    text = ("Ebenso ist „darüber hinaus“ seltener [[beleg:E_query_count_28]], und "
            "„gleichzeitig/zugleich“ steht in beiden Registern [[beleg:E_run_cqlf_query_17]].")
    assert modul._unverifizierte_zitate(text, [_ZAEHLUNG, _KWIC]) == []


def test_ein_erfundenes_beispiel_wird_weiter_gemeldet():
    text = "Die KI-Fassung schreibt oft „technisch sicher und zugleich nur für berechtigte Behörden zugänglich“."
    assert len(modul._unverifizierte_zitate(text, [_TREFFER, _ZAEHLUNG, _KWIC])) == 1


def test_ein_satzinitialer_beleg_deckt_das_zitat_im_satzinneren():
    """Lesung Q4-Reproduktion, A2: die Belegzeile beginnt mit „Darüber hinaus“, die Antwort
    zitiert im Satz „darüber hinaus …“. Gleiche Woerter, andere Schreibung am Satzanfang."""
    zeile = {"id": "E_run_cqlf_query_30", "tool": "run_cqlf_query", "query": json.dumps({"query": "hinaus"}),
             "grounding_surface": ['kwic[0] "Darüber hinaus seien Stimmen gekauft worden"']}
    text = "Die Fassung schreibt, „darüber hinaus seien Stimmen gekauft worden“ [[beleg:E_run_cqlf_query_30]]."
    assert modul._unverifizierte_zitate(text, [zeile]) == []
    erfunden = "Die Fassung schreibt, „darüber hinaus seien Stimmen verkauft worden“ [[beleg:E_run_cqlf_query_30]]."
    assert modul._unverifizierte_zitate(erfunden, [zeile]) == ["darüber hinaus seien Stimmen verkauft worden"]
