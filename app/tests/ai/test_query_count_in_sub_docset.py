"""The contrast recipe permits the same word to be counted in a child docset."""

from candyconc.candyconc_copilot.recipes import RECIPES_BY_ID


def test_beide_naehte_erlauben_das_teil_docset():
    rezept = RECIPES_BY_ID["kontrast"]
    for wo, text in (("briefing", rezept.briefing), ("schritt 4", rezept.schritte[3].tool_hinweis)):
        assert "Teil-Docset" in text, wo
        assert "nur fuer eine Gegenprobe" not in text and "nur fuer eine \nGegenprobe" not in text, wo
