"""A heading followed by a populated subheading is not an empty section."""

from candyconc.candyconc_copilot.table_promise_check import leere_abschnitte, ohne_leere_abschnitte

_TEXT = ("## Mittelstück der Lücke\n\nText.\n\n"
         "## Fünf Belege aus den auffälligsten Modellen\n\n"
         "### GPT-5.4 mini\n\n1. Beleg\n\n"
         "### GPT-OSS 20B\n\n1. Beleg\n")


def test_ueberschrift_ueber_unterabschnitten_bleibt():
    assert leere_abschnitte(_TEXT) == []
    assert ohne_leere_abschnitte(_TEXT) == _TEXT


def test_ueberschrift_vor_gleichrangiger_bleibt_leer():
    assert leere_abschnitte("## Leer\n\n## Voll\n\nText.\n") == ["## Leer"]
