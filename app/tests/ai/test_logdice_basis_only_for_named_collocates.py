# -*- coding: utf-8 -*-
"""The logDice note explains only collocates whose values the answer names."""

from __future__ import annotations

from candyconc.candyconc_copilot import measure_basis
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

AUFRUF = {'docset_id': '4c85f80f53de4a41b367957913f7a955', 'term': 'bedeutet', 'window': 5}
ERGEBNIS = {'status': 'success',
 'requested_term': 'bedeutet',
 'effective_term': 'bedeutet',
 'term_mode': 'surface_or_cql',
 'min_freq': 5,
 'node_frequency': 124,
 'window': 5,
 'within_sentence': True,
 'sort_by': 'logdice',
 'result_count': 22,
 'rows': [{'word': 'Quarantäne',
           'f': 35,
           'f2': 162,
           'observed': 35,
           'expected': 0.49,
           'mi': 6.1624,
           'mi3': 16.421,
           'lmi': 215.6848,
           'npmi': 0.4797,
           'z': 49.3702,
           'chi2_cell': 2437.42,
           't': 5.83,
           'll': 239.51,
           'dice': 0.07454739084132056,
           'logdice': 11.9694,
           'logdice_window': 10.2543,
           'log_ratio': 6.524,
           'lrc': 5.2487,
           'delta_p_nc': 0.0446,
           'delta_p_cn': 0.2132,
           'rank': 1},
          {'word': 'sehr',
           'f': 7,
           'f2': 647,
           'observed': 7,
           'expected': 1.95,
           'mi': 1.8427,
           'mi3': 7.4574,
           'lmi': 12.8991,
           'npmi': 0.1215,
           'z': 3.6138,
           'chi2_cell': 13.06,
           't': 1.91,
           'll': 7.86,
           'dice': 0.009831460674157303,
           'logdice': 8.2168,
           'logdice_window': 7.3316,
           'log_ratio': 1.9525,
           'lrc': 0.0,
           'delta_p_nc': 0.0065,
           'delta_p_cn': 0.0078,
           'rank': 15}]}

#: Beide Saetze woertlich aus der Synthese.
SATZ_QUARANTAENE = (
    "Bei human-*bedeutet* dominieren Inhaltswörter wie *Quarantäne* mit logDice 11,97 "
    "[[beleg:E_collocate_stats_27]], *allen* mit 27 [[beleg:E_collocate_stats_27]] und "
    "*dass* mit 40 [[beleg:E_collocate_stats_27]]."
)
SATZ_GEMINI = (
    "nahe human 216 [[beleg:E_query_count_13]] bei 838,5 [[beleg:E_query_count_13]], gegen "
    "gemini 2 [[beleg:E_query_count_13]] bei 8,2 [[beleg:E_query_count_13]], qwen 6 "
    "[[beleg:E_query_count_13]] bei 24,4 [[beleg:E_query_count_13]] und teuken 0 "
    "[[beleg:E_query_count_13]]."
)


def _posten():
    return [make_evidence_item(
        item_id="E_collocate_stats_27", tool="collocate_stats", tool_call_id="c27",
        query=dict(AUFRUF), output=dict(ERGEBNIS), analysis_family="").to_dict()]


def test_collocate_named_with_its_value_gets_its_basis():
    saetze = measure_basis.saetze(SATZ_QUARANTAENE + "\n\n" + SATZ_GEMINI, _posten())
    assert any("„Quarantäne“" in s for s in saetze), saetze


def test_value_elsewhere_does_not_explain_an_unnamed_collocate():
    saetze = measure_basis.saetze(SATZ_QUARANTAENE + "\n\n" + SATZ_GEMINI, _posten())
    assert not any("„sehr“" in s for s in saetze), saetze


def test_sentence_keeps_its_comma():
    saetze = measure_basis.saetze(SATZ_QUARANTAENE, _posten())
    assert saetze == [
        "logDice für „Quarantäne“ entsteht aus Kookkurrenz 35, Korpusfrequenz des "
        "Kollokats 162 und Knotenfrequenz 124: 14 + log2(2 · f / (Knoten + f2))."
    ]


def test_ordinal_collocate_in_same_sentence_still_counts():
    """„7.“ als Kollokat: der Punkt der Ordnungszahl trennt keinen Satz."""
    ergebnis = dict(ERGEBNIS)
    zeile = dict(ERGEBNIS["rows"][0], word="7.", logdice=9.68, f=682, f2=15048)
    ergebnis["rows"] = [zeile]
    posten = [make_evidence_item(item_id="E_collocate_stats_13", tool="collocate_stats",
                                 tool_call_id="c13", query=dict(AUFRUF), output=ergebnis,
                                 analysis_family="").to_dict()]
    antwort = "stärkste Kollokate sind Nummerierungen 7. mit logDice 9,68 [[beleg:E_collocate_stats_13]]."
    assert any("„7.“" in s for s in measure_basis.saetze(antwort, posten))
