"""Quoted patterns from the question need no notice unless asserted as corpus evidence."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_FRAGE = "Mir fällt beim Lesen auf, dass die Maschinenfassungen oft nicht nur ... sondern auch schreiben."
_POSTEN = [{"grounding_surface": ["kwic[0] etwas ganz anderes"]}]


def test_abstandszitat_aus_der_frage_ohne_hinweis():
    text = "Sie verteilt sich nicht gleichmäßig über „die Maschinenfassungen“. GPT-5.4 mini liegt vorn."
    assert modul._unverifizierte_zitate(text, _POSTEN, _FRAGE) == []


def test_fragephrase_als_beleg_wird_weiter_gemeldet():
    text = "Ein Beleg lautet „die Maschinenfassungen“ [[beleg:E_run_cqlf_query_5]]."
    assert modul._unverifizierte_zitate(text, _POSTEN, _FRAGE) == ["die Maschinenfassungen"]


def test_ohne_frage_bleibt_alles_wie_bisher():
    # Seit dem Beleganspruch (test_quote_notice_only_for_evidence_claims) prueft
    # der Hinweis nur Anfuehrungen, die sich als Korpuszeile ausgeben. Ohne
    # Frage deckt die Frage nichts, eine solche Anfuehrung bleibt gemeldet.
    text = "Die Fassung schreibt „die Maschinenfassungen“."
    assert modul._unverifizierte_zitate(text, _POSTEN) == ["die Maschinenfassungen"]
