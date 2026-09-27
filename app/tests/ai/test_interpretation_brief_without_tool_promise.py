# -*- coding: utf-8 -*-
"""Der Deutungsauftrag der werkzeuglosen Aufrufe verspricht keine Werkzeuge.

Der Systemtext der Synthese sagte "Es gibt keine Werkzeuge mehr", dann im
eingebetteten Deutungsauftrag "FÜHRE offene Teilfragen selbst aus. Die
Werkzeuge sind da.", und danach per Zusatz "Offene Teilfragen führst du
nicht mehr aus". Der Widerspruch blieb dem Modell zur Aufloesung ueberlassen.
"""

from __future__ import annotations

import unittest

# Erst die Modulnaht der echten Copilot-Module, wie test_interpretation_synthesis.py:
# ein frueherer Direktimport legte sonst ein zweites Modulobjekt an, und
# deren Patches trafen das falsche.
from tests.ai import _real_copilot  # noqa: F401

from candyconc.candyconc_copilot.interpretation_synthesis import (
    deutungs_synthese_messages,
    gutachten_abschnitt_messages,
)
from candyconc.candyconc_copilot.prompts import (
    DEUTUNGS_AUFTRAG,
    DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE,
    SYSTEM_PROMPT,
)

_VERSPRECHEN = "Die Werkzeuge sind da"


class TestToolFreeCallsGetNoToolPromise(unittest.TestCase):
    def test_synthesis_system_text_has_no_tool_promise(self):
        system, _user = deutungs_synthese_messages("F", "E", "K", "Entwurf")
        self.assertIn("Es gibt keine Werkzeuge mehr", system["content"])
        self.assertNotIn(_VERSPRECHEN, system["content"])
        self.assertNotIn("FÜHRE offene Teilfragen selbst aus", system["content"])
        self.assertIn("BEANTWORTE die Frage im ersten Absatz", system["content"])
        self.assertIn("UNSICHERHEIT benenne präzise", system["content"])

    def test_report_section_system_text_has_no_tool_promise(self):
        system, _user = gutachten_abschnitt_messages("F", 1, "Titel", "Auftrag", "E")
        self.assertIn("Es gibt keine Werkzeuge mehr", system["content"])
        self.assertNotIn(_VERSPRECHEN, system["content"])

    def test_the_tool_phase_keeps_the_full_brief(self):
        self.assertIn(DEUTUNGS_AUFTRAG, SYSTEM_PROMPT)
        self.assertIn(_VERSPRECHEN, DEUTUNGS_AUFTRAG)

    def test_only_the_tool_bullet_differs(self):
        self.assertNotEqual(DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE, DEUTUNGS_AUFTRAG)
        entfernt = len(DEUTUNGS_AUFTRAG) - len(DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE)
        self.assertLess(entfernt, 300, "mehr als der Werkzeugpunkt entfiel")
        for zeile in DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE.splitlines():
            self.assertIn(zeile, DEUTUNGS_AUFTRAG)


if __name__ == "__main__":
    unittest.main()
