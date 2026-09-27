"""P5 (Runde 2): der verlauf-Rezeptvertrag traegt die Wegbereiter-Werkzeuge.

Messung diachronie-2: der Turn sollte den Trend auf einem FDP-Docset
rechnen, durfte aber nur trend_analysis und landete auf dem
Gesamtkorpus — die falsche Frage exakt beantwortet.
"""

from candyconc.candyconc_copilot.recipes_data import RECIPES_DATA


def test_verlauf_rezept_bereitellt_docset_werkzeuge_vor():
    verlauf = next(r for r in RECIPES_DATA if r["id"] == "verlauf")
    wegbereiter = set(verlauf.get("wegbereiter_tools") or ())
    assert {"create_docset", "metadata_values"} <= wegbereiter
