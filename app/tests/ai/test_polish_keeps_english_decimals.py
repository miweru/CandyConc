"""The final polish folds only the whitespace a removed ID leaves behind.

English probe of 2026-09-27, runs b1, b2, c2: the model wrote "log_ratio .85
[CI .68–1.03]" and "expected .64", the delivered answer read
"log_ratio.85 [CI.68–1.03]" and "expected.64". ``_scrub_internal_ids``
dropped every space before ``,.;:!?`` outside quotations, also when no ID had
been removed.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.recipe_runtime import (
    _scrub_internal_ids,
    final_answer_polish,
)

# Recorded synthesis of run b1 (deutungs_synthese.txt), one paragraph.
B1 = (
    "The *America/freedom* frame is the stable Republican signature: *America* occurs 4,022 "
    "words per million (pmw) in GOP addresses versus 2,225 in Democratic ones, log_ratio .85 "
    "[CI .68–1.03] [[beleg:E_keyness_4]]; *freedom* is about twice as frequent (1,893 vs 916 "
    "pmw, log_ratio 1.05 [CI .78–1.32]) and appears in 33 of the 36 Republican texts "
    "[[beleg:E_run_cqlf_query_5]]. *free* is also overrepresented (1,549 vs 943 pmw, "
    "log_ratio .71 [CI .44–.99]) [[beleg:E_keyness_4]]."
)
# Recorded synthesis of run c2, one bullet.
C2 = ("*global* f=20 vs expected .64 (≈31×), *expanding* f=17 vs expected .46 (≈37×), and "
      "*healthy* f=12 vs expected .28 (≈43×) [[beleg:E_collocate_stats_1]].")


def test_english_short_decimals_survive_the_scrub():
    assert _scrub_internal_ids(B1) == B1
    assert _scrub_internal_ids(C2) == C2


def test_english_short_decimals_survive_the_whole_polish():
    poliert, _ = final_answer_polish(B1, deckung_wache=False)
    assert "log_ratio .85 [CI .68–1.03]" in poliert
    assert "log_ratio .71 [CI .44–.99]" in poliert
    poliert, _ = final_answer_polish(C2, deckung_wache=False)
    assert "expected .64" in poliert and "expected .28" in poliert


def test_whitespace_left_by_a_removed_id_is_still_folded():
    assert _scrub_internal_ids("Der Wert ist 5 (E_keyness_4).") == "Der Wert ist 5."
    assert _scrub_internal_ids("Der Wert ist 5 E_keyness_4.") == "Der Wert ist 5."
    assert _scrub_internal_ids("Die Route E_collocate_stats_2 ist intern.") == "Die Route ist intern."
    assert _scrub_internal_ids("Wert 5 (E_keyness_4, Zeile 3) steht da.") == "Wert 5 (Zeile 3) steht da."
    assert _scrub_internal_ids("Wert 5  ev3  steht da.") == "Wert 5 steht da."


def test_text_without_an_id_keeps_its_spacing():
    text = "Der Beleg „der Denunziant . Die Menschen“ steht so , wie er steht ."
    assert _scrub_internal_ids(text) == text
