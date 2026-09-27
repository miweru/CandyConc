"""Quote verification tolerates Markdown and explicit ellipsis between supported words."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_POSTEN = [{"grounding_surface": [
    "kwic[0] Demokratie . \n\n * * [Fazit] : * * Die Wissenschaftsfreiheit ist kein Luxus",
    "kwic[1] Wer den * * digitalen Wandel gestalten will , braucht",
    "kwic[2] Das ist [nicht] nur ein Gesetz , sondern ein Versprechen",
    "kwic[3] Hier liegt die eigentliche Pointe des Entwurfs",
]}]


def test_markdown_der_belegzeile_macht_kein_zitat_unverifizierbar():
    text = ("Beleg: „Demokratie. **Fazit:** Die Wissenschaftsfreiheit ist kein“ und "
            "„Wer den digitalen Wandel gestalten will“.")
    assert modul._unverifizierte_zitate(text, _POSTEN) == []


def test_musterbenennungen_mit_auslassung_werden_als_auslassung_gelesen():
    text = "Die Synthese nennt „nicht …, sondern …“ und „die eigentliche X“ als Muster."
    assert modul._unverifizierte_zitate(text, _POSTEN) == []


def test_ein_erfundenes_zitat_wird_weiter_gemeldet():
    text = "Beleg: „Die KI schreibt stets in makellosen Sätzen“."
    assert modul._unverifizierte_zitate(text, _POSTEN) == ["Die KI schreibt stets in makellosen Sätzen"]


def test_eine_auslassung_rettet_kein_erfundenes_zitat():
    text = "Beleg: „Die Wissenschaftsfreiheit ist kein … makelloser Satz der Regierung“."
    assert len(modul._unverifizierte_zitate(text, _POSTEN)) == 1
