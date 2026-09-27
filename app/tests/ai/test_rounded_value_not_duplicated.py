"""Ein gerundeter Wert wird nicht neben seinen Rohwert gesetzt.

LIVE am 2026-09-01, in einer ausgelieferten Antwort:

    „sondern" in KI-Fassungen 4362,3 4362.29273365558 pmw

Ein Wert, zweimal, einmal lesbar und einmal roh. Die Prompt-Regel
("Marker DIREKT hinter den Wert, VOR das Einheitenwort") war eingehalten,
nur die Pruefung dahinter kannte keine Rundung: sie verglich exakt, sah
"4362,3" nicht als Wiedergabe von 4362.29273365558 und setzte den
Evidenzwert ein zweites Mal.

ZWEI FALLEN, beide beim Bau aufgelaufen.

Die Rundungspruefung stand zuerst hinter einem ``if not
normalised.isdigit()`` und wurde nie erreicht: ``_grouping_stripped``
entfernt den Punkt, weil er im Deutschen gruppiert, und damit sieht
4362.29273365558 wie eine reine Ziffernfolge aus.

Und die Schreibung ist mehrdeutig. "4362,3" ist deutsch drei Zehntel,
"18.761" ist deutsch achtzehntausend und englisch achtzehn Komma sieben.
Die Antwort traegt BEIDE: Modelltext deutsch, Evidenzwert englisch. Wer
sich fuer eine Konvention entscheidet, liegt bei der anderen falsch, also
werden beide Lesarten geprueft.
"""

from __future__ import annotations

import unittest

from candyconc.candyconc_copilot.grounding_refs import _value_already_stated


class EineRundungGiltAlsGenannt(unittest.TestCase):
    def test_der_live_fall(self):
        self.assertTrue(
            _value_already_stated("in KI-Fassungen 4362,3 ", "4362.29273365558")
        )

    def test_jede_stellenzahl(self):
        for geschrieben, erwartet in (
            ("4362", True), ("4362,3", True), ("4362,29", True),
            ("4362,293", True), ("4363", False), ("4400", False),
        ):
            with self.subTest(geschrieben=geschrieben):
                self.assertIs(
                    _value_already_stated(f"Rate {geschrieben} ", "4362.29273365558"),
                    erwartet,
                )

    def test_beide_schreibungen(self):
        self.assertTrue(_value_already_stated("logDice 9,45 ", "9.45"))
        self.assertTrue(_value_already_stated("logDice 9.45 ", "9.45"))
        self.assertTrue(_value_already_stated("Treffer 18.761 ", "18761"))


class EineFALSCHEZahlBleibtSichtbar(unittest.TestCase):
    """Die Wache darf nicht zur Durchreiche werden.

    Wer einen falschen Wert schreibt, bekommt den echten danebengesetzt,
    und die Abweichung wird sichtbar. Genau dafuer steht die Pruefung.
    """

    def test_eine_falsche_rundung_gilt_nicht_als_genannt(self):
        self.assertFalse(_value_already_stated("Wert 0,09 ", "0.083333"))
        self.assertFalse(_value_already_stated("Rate 4400 ", "4362.29273365558"))

    def test_eine_ganz_andere_zahl_erst_recht_nicht(self):
        self.assertFalse(_value_already_stated("Treffer 12, ", "98"))

    def test_zu_viele_stellen_werden_nicht_geglaubt(self):
        """Sieben Nachkommastellen sind keine Rundung mehr, sondern Rauschen."""
        self.assertFalse(
            _value_already_stated("Wert 0,0833333 ", "0.08333329999")
        )


class DasBisherigeVerhaltenBleibt(unittest.TestCase):
    def test_ganze_zahlen_und_text(self):
        self.assertTrue(_value_already_stated("Treffer 212 ", "212"))
        self.assertTrue(_value_already_stated("test, train ", "test, train"))
        self.assertTrue(_value_already_stated("nach `score_key = logdice` ", "logDice"))

    def test_leeres_bleibt_falsch(self):
        self.assertFalse(_value_already_stated("", "212"))
        self.assertFalse(_value_already_stated("Treffer 212 ", ""))


if __name__ == "__main__":
    unittest.main()
