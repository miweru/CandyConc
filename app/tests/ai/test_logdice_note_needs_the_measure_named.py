# -*- coding: utf-8 -*-
"""A logDice note requires the sentence to name the measure explicitly."""

from __future__ import annotations

from candyconc.candyconc_copilot import measure_basis
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

PROBLEM = {"word": "Problem", "f": 1202, "f2": 34452, "observed": 1202, "expected": 28.03,
           "logdice": 9.6686, "log_ratio": 5.473, "lrc": 5.2555, "rank": 1}
SELBST = {"word": "selbst", "f": 71, "f2": 102806, "observed": 71, "logdice": 4.3166, "rank": 400}


def _posten(*zeilen):
    ergebnis = {"status": "success", "requested_term": "eigentliche", "node_frequency": 13945,
                "window": 5, "sort_by": "logdice", "rows": [dict(z) for z in zeilen]}
    return [make_evidence_item(item_id="E_collocate_stats_33", tool="collocate_stats",
                               tool_call_id="c33",
                               query={"sort_by": "logdice", "term": "eigentliche", "window": 5},
                               output=ergebnis, analysis_family="").to_dict()]


#: Woertlich aus der Antwort.
SATZ_FAKTOR = ("Faktor 4,3 zugunsten KI selbst gerechnet [[beleg:E_query_count_12]], Intervalle "
               "weit disjunkt, Streuung dp 0,0595 [[beleg:E_query_count_12]] zu klein, um "
               "Klumpung als Erklärung zuzulassen.")
SATZ_PROBLEM = ("Die Kollokationen zu `eigentliche` bestätigen die essentialisierende Lesart: "
                "`Problem` Rang 1 mit logDice 9,67 [[beleg:E_collocate_stats_33]] bei 1.202 "
                "Fensterbelegen [[beleg:E_collocate_stats_33]].")


def test_ordinary_word_next_to_a_factor_gets_no_basis():
    saetze = measure_basis.saetze(SATZ_FAKTOR, _posten(PROBLEM, SELBST))
    assert not any("„selbst“" in s for s in saetze), saetze


def test_collocate_named_with_logdice_keeps_its_basis():
    saetze = measure_basis.saetze(SATZ_PROBLEM + "\n\n" + SATZ_FAKTOR, _posten(PROBLEM, SELBST))
    assert [s for s in saetze if "„Problem“" in s], saetze
    assert not any("„selbst“" in s for s in saetze), saetze


def test_table_row_under_a_logdice_header_counts():
    tabelle = "| Kollokat | f | logDice |\n|---|---|---|\n| Problem | 1.202 | 9,67 |"
    saetze = measure_basis.saetze(tabelle, _posten(PROBLEM))
    assert [s for s in saetze if "„Problem“" in s], saetze
