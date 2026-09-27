# -*- coding: utf-8 -*-
"""The draft handed to the synthesis keeps which row it cites.

Found by the flow reviewer on 2026-09-26: entwurf_marker_vereinfachen turned
every ``{{ev:ID.path}}`` into ``{{ev:ID}}``, 1,252 row pointers in 37 of 39
drafts. In Muse cycle 8 (konstr-scharnier-dreigliedrig) the draft cited
``{{ev:E_run_cqlf_query_25.rows[22]}}`` and the synthesis used hit 0 of the same
call, which does not show the pattern the question asked for.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.interpretation_synthesis import entwurf_marker_vereinfachen


def test_kwic_row_becomes_the_package_hit_number():
    text = "Beispiel 1 {{ev:E_run_cqlf_query_25.rows[22]}}."
    assert entwurf_marker_vereinfachen(text) == "Beispiel 1 {{ev:E_run_cqlf_query_25}} (Treffer 22)."


def test_table_row_becomes_the_package_line_number():
    text = "spoken 610,3 {{ev:E_query_count_2.rows[9].per_million}}"
    assert entwurf_marker_vereinfachen(text) == "spoken 610,3 {{ev:E_query_count_2}} (Zeile 9)"


def test_scalar_field_stays_a_plain_marker():
    text = "3082 {{ev:E_query_count_1.total}} und {{ev:E_keyness_4}}"
    assert entwurf_marker_vereinfachen(text) == "3082 {{ev:E_query_count_1}} und {{ev:E_keyness_4}}"
