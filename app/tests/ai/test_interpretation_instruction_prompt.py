"""Probe: Der System-Prompt traegt einen Deutungsauftrag mit Recency.

Ursache (Befund Arm 4, Urteile vom 2026-09-04): Der bisherige Prompt
schloss mit Verifikationsverboten (NICHT_VERHANDELBAR doppelt, VERIFIKATION
zuletzt). Recency lehrte das Modell Vorsicht statt Analyse: median 1,5
deutende Saetze gegen 32,5 in der Referenz, Listen offener Teilfragen
statt ausgefuehrter Rechnungen, Methodikabsaetze statt Deutung.

Ohne die Aenderung ist diese Probe ROT: der Deutungsauftrag fehlt und
der letzte Block ist ein Verbot statt des Auftrags.

Der Prompt wird ueber den _real_copilot-Loader geladen, weil
tests/conftest.py fuer tests/ai einen Stub des copilot-Pakets
installiert (siehe dessen Docstring).
"""
import unittest

from tests.ai import _real_copilot

SYSTEM_PROMPT = _real_copilot.prompts.SYSTEM_PROMPT
GET = _real_copilot.prompts.get_system_prompt


class TestDeutungsauftrag(unittest.TestCase):
    def test_auftrag_ist_vorhanden(self):
        self.assertIn("Deutung, nicht Protokoll", SYSTEM_PROMPT)
        self.assertIn("Deine eigene Arbeit", SYSTEM_PROMPT)

    def test_auftrag_hat_recency_und_nicht_die_verbote(self):
        self.assertLess(
            SYSTEM_PROMPT.rfind("Verifikation"),
            SYSTEM_PROMPT.rfind("Deutung, nicht Protokoll"),
            "Der Deutungsauftrag muss NACH der Verifikation stehen "
            "(Recency), sonst lehrt der Prompt wieder Vorsicht.",
        )
        self.assertTrue(
            SYSTEM_PROMPT.rstrip().endswith("</deutungsauftrag>"),
            "Der letzte Promptblock muss der Deutungsauftrag sein, "
            "nicht noch einmal nicht_verhandelbar.",
        )
        self.assertNotIn(
            "</nicht_verhandelbar>\n</deutungsauftrag>",
            SYSTEM_PROMPT,
        )

    def test_zahlendisziplin_bleibt(self):
        # Die Trennung laut Ziel: Zahlen verifiziert, Analyse frei.
        # Die Zahlendisziplin (am Anfang) darf nicht verschwinden.
        self.assertIn("Nie schätzen", SYSTEM_PROMPT)
        self.assertIn("exakt und transparent nachrechenbar", SYSTEM_PROMPT)
        self.assertIn("status==\"success\"", SYSTEM_PROMPT)

    def test_get_system_prompt_liefert_auftrag(self):
        self.assertIn("Deutung, nicht Protokoll", GET())


if __name__ == "__main__":
    unittest.main()
