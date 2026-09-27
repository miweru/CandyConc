# -*- coding: utf-8 -*-
"""Interpretation submission reaches the API response."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from candyconc.tooling.tool_selection import (  # noqa: E402
    _visible_product_tools,
    select_tools_for_prompt,
)


def _spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


_ABGABE = _spec("deutung_abgeben")
_FREMD = _spec("irgendein_nicht_produkt_werkzeug")


class Produktsichtbarkeit(unittest.TestCase):
    def test_die_abgabe_durchdraengt_die_produktsichtbarkeit(self):
        sichtbar = _visible_product_tools([_ABGABE, _FREMD])
        namen = {t["function"]["name"] for t in sichtbar}
        self.assertIn("deutung_abgeben", namen)

    def test_ein_fremdes_nicht_produkt_werkzeug_bleibt_blockiert(self):
        sichtbar = _visible_product_tools([_FREMD])
        self.assertEqual(sichtbar, [])


class Verengung(unittest.TestCase):
    """Klasse A gegen Klasse B auf dem vollen Auswahl-Pfad."""

    def test_verengte_auswahl_behaelt_die_abgabe(self):
        # Ein offensichtlicher Prompt-SHAPE (Frequenzfrage) verengt die
        # Auswahl — die Abgabe muss trotzdem im Angebot stehen.
        frage = "Wie oft kommt Zeit im Korpus vor?"
        auswahl = select_tools_for_prompt(
            frage, [_spec("query_count"), _spec("frequency_list"), _ABGABE])
        namen = {t["function"]["name"] for t in auswahl}
        self.assertIn("deutung_abgeben", namen, namen)

    def test_unklare_frage_behaelt_die_abgabe_auch(self):
        auswahl = select_tools_for_prompt("Nonsense?", [_spec("query_count"), _ABGABE])
        namen = {t["function"]["name"] for t in auswahl}
        self.assertIn("deutung_abgeben", namen, namen)

    def test_fremdes_werkzeug_erscheint_nie_in_der_auswahl(self):
        auswahl = select_tools_for_prompt(
            "Wie oft kommt Zeit vor?", [_spec("query_count"), _FREMD])
        namen = {t["function"]["name"] for t in auswahl}
        self.assertNotIn("irgendein_nicht_produkt_werkzeug", namen, namen)

    def test_die_abgabe_kommt_nicht_doppelt(self):
        # Der Lifter haengt nur an, was fehlt: ein bereits vorhandenes
        # Abgabe-Spec wird nicht dupliziert.
        auswahl = select_tools_for_prompt(
            "Wie oft kommt Zeit vor?", [_spec("query_count"), _ABGABE])
        anzahl = sum(
            1 for t in auswahl if t["function"]["name"] == "deutung_abgeben")
        self.assertEqual(anzahl, 1)


if __name__ == "__main__":
    unittest.main()


class DispatchWache(unittest.TestCase):
    """Die dritte Wache: ohne Produkt-Bindung ist Dispatch sonst tot."""

    def test_die_abgabe_ist_ohne_bindung_dispatchable(self):
        from candyconc.tooling.tool_selection import (
            is_tool_dispatchable_for_principal,
        )
        ri = {"deutung_abgeben": {"read_only": True}}
        self.assertTrue(is_tool_dispatchable_for_principal(
            "deutung_abgeben", runtime_info=ri, allowed_tools=None,
            release_mode=False))

    def test_ein_fremdes_werkzeug_ohne_bindung_bleibt_gesperrt(self):
        from candyconc.tooling.tool_selection import (
            is_tool_dispatchable_for_principal,
        )
        ri = {"irgendein_werkzeug": {"read_only": True}}
        self.assertFalse(is_tool_dispatchable_for_principal(
            "irgendein_werkzeug", runtime_info=ri, allowed_tools=None,
            release_mode=False))

    def test_ohne_runtime_info_ist_auch_die_abgabe_gesperrt(self):
        from candyconc.tooling.tool_selection import (
            is_tool_dispatchable_for_principal,
        )
        self.assertFalse(is_tool_dispatchable_for_principal(
            "deutung_abgeben", runtime_info={}, allowed_tools=None,
            release_mode=False))

    def test_allowed_tools_beschraenkt_auch_die_abgabe(self):
        from candyconc.tooling.tool_selection import (
            is_tool_dispatchable_for_principal,
        )
        ri = {"deutung_abgeben": {"read_only": True}}
        self.assertFalse(is_tool_dispatchable_for_principal(
            "deutung_abgeben", runtime_info=ri,
            allowed_tools=["query_count"], release_mode=False))

    def test_ende_zu_ende_durch_alle_drei_wachen(self):
        from candyconc.tooling.tool_selection import (
            filter_dispatchable_tools_for_principal,
        )
        frage = "Wie oft kommt Zeit im Korpus vor?"
        tools = [_spec("query_count"), _spec("frequency_list"), _ABGABE, _FREMD]
        auswahl = select_tools_for_prompt(frage, tools)
        final = filter_dispatchable_tools_for_principal(
            auswahl,
            runtime_info={n: {"read_only": True} for n in
                          ("query_count", "frequency_list", "deutung_abgeben")},
            allowed_tools=None, release_mode=False)
        namen = [t["function"]["name"] for t in final]
        self.assertIn("deutung_abgeben", namen, namen)
        self.assertNotIn("irgendein_nicht_produkt_werkzeug", namen, namen)
