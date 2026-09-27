"""H11.4: Die Antwort-Politur putzt, sie entkernt nicht.

Gemessener Anlass (qwen3.8-27b gegen den Testindex, 2026-08-15): eine
2571 Zeichen lange KWIC-Analyse kam mit 485 Zeichen und leeren Belegpunkten
beim Nutzer an. Schuldig war ``_trim_dangling_quote_spans``: die Pruefung
lief zeilenweise, zaehlte ``„`` nur gegen ``“`` und hielt jede
```-Fence-Zeile fuer eine offene Backtick-Spanne.

Die Tests pinnen beide Richtungen: der Schutz gegen Kuerzungen mitten im
Zitat bleibt, der Kahlschlag ist weg.
"""

import unittest

from candyconc.candyconc_copilot.recipe_runtime import (
    POLITUR_VERLUST_SCHWELLE,
    _trim_dangling_quote_spans,
    final_answer_polish,
)


class TrimDanglingQuoteSpans(unittest.TestCase):
    def test_gemischte_anfuehrungszeichen_bleiben_unangetastet(self):
        """Modelle mischen typografisch und gerade — das ist kein Abbruch."""
        text = (
            '- Beleg: „Deutschland geht unter" markiert Bedrohung.\n'
            "- Beleg: „Deutschland“ steht fuer die Institution.\n"
            "Deutung: zwei klar getrennte Gebrauchsweisen."
        )
        self.assertEqual(_trim_dangling_quote_spans(text), text)

    def test_code_fences_ueberleben(self):
        text = "```text\nDeutschland | geht | unter\n```\n\nDeutung: klar."
        self.assertEqual(_trim_dangling_quote_spans(text), text)

    def test_zeilen_in_fences_werden_nicht_geprueft(self):
        """Innerhalb eines Fences ist ein einzelner Backtick Nutztext."""
        text = "```\nQuery-Rest: `unvollstaendig\n```\nDeutung: klar."
        self.assertEqual(_trim_dangling_quote_spans(text), text)

    def test_unbalanciertes_zitat_mitten_im_text_bleibt(self):
        """Ein Modell-Tippfehler in Zeile 1 darf Zeile 2 nicht kosten."""
        text = "Zeile mit „offenem Zitat\nDanach folgt der Schlusssatz."
        self.assertEqual(_trim_dangling_quote_spans(text), text)

    def test_offenes_zitat_am_textende_wird_gekappt(self):
        """Der eigentliche Zweck: ein Stream-Abbruch endet nie im Zitat."""
        text = "Kernbefund: klar.\n- Beleg: „Deutschland geht"
        self.assertEqual(_trim_dangling_quote_spans(text), "Kernbefund: klar.\n- Beleg:")

    def test_offener_backtick_am_textende_wird_gekappt(self):
        text = 'Kernbefund: klar.\n- Query: `[word="X"]'
        self.assertEqual(_trim_dangling_quote_spans(text), "Kernbefund: klar.\n- Query:")

    def test_substanzlose_restzeile_faellt_ganz(self):
        text = "Kernbefund: klar.\n- „Deutschland geht"
        self.assertEqual(_trim_dangling_quote_spans(text), "Kernbefund: klar.")

    def test_leerzeilen_nach_dem_ende_verschieben_die_pruefung_nicht(self):
        text = "Kernbefund: klar.\n- Beleg: „Deutschland geht\n\n"
        self.assertEqual(
            _trim_dangling_quote_spans(text), "Kernbefund: klar.\n- Beleg:\n\n"
        )


class PoliturBehaeltSubstanz(unittest.TestCase):
    #: Woertlich nachgebaut aus dem gemessenen Ausfall: Belegzeilen mit
    #: gemischten Anfuehrungszeichen, dazwischen ein Fence-Block.
    ANTWORT = (
        "**Kernbefund:** In 105 Treffern tritt „Deutschland\" vor allem als "
        "politischer Bezugspunkt auf.\n\n"
        "**Belege:**\n"
        "- **Bedrohung:** „Deutschland geht unter\" (Beleg 1)\n"
        "- **Zensurvorwurf:** „In Deutschland darf man nichts mehr sagen\" "
        "(Beleg 2)\n"
        "- **Forderung:** „Deutschland braucht endlich eine Wende\" (Beleg 3)\n"
        "- **Gemeinschaft:** „Wir in Deutschland halten zusammen\" (Beleg 4)\n\n"
        "```text\nDeutschland | geht | unter\n```\n\n"
        "**Deutung:** Das Wort markiert den Raum politischer Legitimation. "
        "Es tritt haeufiger in Forderungen als in Beschreibungen auf.\n\n"
        "**Grenzen:** Die Analyse stuetzt sich auf 50 von 105 Treffern."
    )

    def test_politur_laesst_die_belege_stehen(self):
        poliert, _ = final_answer_polish(self.ANTWORT)
        for beleg in ("geht unter", "nichts mehr sagen", "eine Wende", "zusammen"):
            self.assertIn(beleg, poliert, f"Beleg '{beleg}' wurde weggeputzt")

    def test_politur_verliert_keine_substanz(self):
        poliert, _ = final_answer_polish(self.ANTWORT)
        self.assertGreater(
            len(poliert),
            len(self.ANTWORT) * (1.0 - POLITUR_VERLUST_SCHWELLE),
            "Die Politur hat mehr Text entfernt als die Befundschwelle erlaubt",
        )

    def test_fence_bleibt_erhalten(self):
        poliert, _ = final_answer_polish(self.ANTWORT)
        self.assertIn("```", poliert)


class RenderResteAusDemQwenLauf(unittest.TestCase):
    """Drei Anzeigefehler aus demselben gemessenen Lauf."""

    def test_klammer_ohne_id_behaelt_die_zeilenangabe(self):
        """``(E_kwic_lines_1, Zeile 3)`` wurde zu ``(, Zeile 3)``."""
        text = "1. Kritik: „Deutschland geht unter“ (E_kwic_lines_1, Zeile 3)."
        poliert, _ = final_answer_polish(text)
        self.assertIn("(Zeile 3)", poliert)
        self.assertNotIn("(,", poliert)
        self.assertNotIn("E_kwic_lines_1", poliert)

    def test_reine_id_klammer_faellt_ganz(self):
        text = "Der Wert stammt aus der Tabelle (E_freq_1)."
        poliert, _ = final_answer_polish(text)
        self.assertNotIn("(", poliert)

    def test_kursives_label_unter_fetter_ueberschrift_faellt(self):
        text = "**Deutung:**\n*Deutung:* Die Belege zeigen ein Muster."
        poliert, _ = final_answer_polish(text)
        self.assertEqual(poliert.count("Deutung"), 1)
        self.assertIn("Die Belege zeigen ein Muster.", poliert)

    def test_ueberschrift_mit_innenliegendem_doppelpunkt_zaehlt(self):
        """``**Deutung:**`` galt bisher nicht als Ueberschriftszeile."""
        text = "**Grenzen:**\n**Grenzen:** Die Stichprobe ist klein."
        poliert, _ = final_answer_polish(text)
        self.assertEqual(poliert.count("Grenzen"), 1)

    def test_label_ohne_doppelpunkt_bleibt_prosa(self):
        """'Deutung der Daten ...' ist kein wiederholtes Label."""
        text = "Deutung\nDeutung der Daten zeigt ein Muster im Korpus."
        poliert, _ = final_answer_polish(text)
        self.assertIn("Deutung der Daten zeigt", poliert)

    def test_doppeltes_zitat_faellt_auf_die_aufgeloeste_fassung(self):
        text = (
            '1. Kritik: „…kein Grund [Deutschland] mit fremden Maennern zu '
            'fluten" „aber noch lange kein Grund Deutschland mit fremden '
            "Maennern zu fluten“ (Zeile 3)."
        )
        poliert, _ = final_answer_polish(text)
        self.assertEqual(poliert.count("fluten"), 1)
        self.assertIn("„aber noch lange kein Grund Deutschland", poliert)
        self.assertNotIn("[Deutschland]", poliert)

    def test_zwei_verschiedene_zitate_bleiben_beide(self):
        text = (
            'Vergleich: „Der Islam gehoert zu Deutschland" '
            "„Regieren uns Linke Marionetten die alles kaputt machen“"
        )
        poliert, _ = final_answer_polish(text)
        self.assertIn("Der Islam gehoert zu Deutschland", poliert)
        self.assertIn("Regieren uns Linke Marionetten", poliert)


class KlassifikatorPraefixRettung(unittest.TestCase):
    """qwen3.8-27b beendet die Antwort nach einem Teilwort-Token.

    Deterministisch reproduziert gegen LM Studio: die Klassifikator-Antwort
    auf die H10-Frage ``h10_assoz_frau`` lautet ``assoziatio`` bei
    ``finish_reason='stop'`` und 4 Tokens. Kein Token-Limit, kein
    Stream-Verlust — das Modell setzt EOS an einer Tokengrenze. Ein
    eindeutiges Praefix rettet das Routing, Mehrdeutiges nicht.
    """

    def test_verkuerzte_antwort_wird_eindeutig_aufgeloest(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            parse_recipe_classifier_reply,
        )

        self.assertEqual(parse_recipe_classifier_reply("assoziatio"), "assoziation")
        self.assertEqual(
            parse_recipe_classifier_reply("gebrauch_kw"), "gebrauch_kwic"
        )

    def test_vollstaendige_antwort_unveraendert(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            parse_recipe_classifier_reply,
        )

        self.assertEqual(parse_recipe_classifier_reply("profil"), "profil")
        self.assertEqual(parse_recipe_classifier_reply("frei"), "")

    def test_zu_kurzes_oder_mehrdeutiges_praefix_rettet_nichts(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            parse_recipe_classifier_reply,
        )

        # Unter vier Zeichen wird nicht geraten.
        self.assertEqual(parse_recipe_classifier_reply("ass"), "")
        # Zwei ids im Text bleiben mehrdeutig.
        self.assertEqual(parse_recipe_classifier_reply("kontrast oder verlauf"), "")
        self.assertEqual(parse_recipe_classifier_reply("xyz"), "")


if __name__ == "__main__":
    unittest.main()


class VorplanGegenKontrakt(unittest.TestCase):
    """H11.4: Ein Kontrakt ohne Werkzeugangabe hungert den Vorplan nicht aus.

    Gemessen an ``h10_freq_frau`` (qwen3.8-27b): die Frage nach Rohzahl und
    Haeufigkeit je Million von ‚Frau‘ wurde mit einer generischen
    Top-10-Frequenzliste beantwortet. Der Vorplan haette
    ``query_count(query='Frau')`` gerufen, wurde aber gegen die leere
    ``allowed_tools``-Liste des Kontrakts gefiltert und fiel weg.
    """

    FRAGE = (
        "Quantifiziere das Auftreten der Wortform ‚Frau‘ im Gesamtbestand: "
        "Nenne Rohzahl und Häufigkeit je eine Million Tokens."
    )
    WERKZEUGE = ("query_count", "frequency_list", "collocate_stats")

    def _plan(self, contract_tools):
        from candyconc.candyconc_copilot.recipe_runtime import preplan_with_contract

        return preplan_with_contract(
            "frequenz", self.FRAGE, None,
            available_tools=self.WERKZEUGE,
            gated_tools={},
            contract_tools=contract_tools,
        )

    @staticmethod
    def _namen(calls):
        return [str((c.get("function") or {}).get("name") or "") for c in calls]

    def test_leerer_kontrakt_laesst_den_vorplan_gelten(self):
        calls, zusatz = self._plan([])
        self.assertEqual(self._namen(calls), ["query_count"])
        self.assertEqual(zusatz, ["query_count"])

    def test_termgebundener_vorplan_ergaenzt_die_kontraktliste(self):
        """Die Frage nennt ‚Frau‘ — das Zaehlwerkzeug muss dazu.

        Ergaenzt, nicht ersetzt: die Entscheidung des Kontrakts bleibt
        erhalten, der Vorplan kommt hinzu.
        """
        calls, zusatz = self._plan(["frequency_list"])
        self.assertEqual(self._namen(calls), ["query_count"])
        self.assertEqual(zusatz, ["frequency_list", "query_count"])

    def test_generischer_vorplan_respektiert_die_kontraktliste(self):
        """Ohne Termbezug bleibt eine ausdrueckliche Einschraenkung stehen.

        Ein semantischer Kontrakt darf auf semantische Werkzeuge
        einschraenken, ohne dass die generische Explorations-Vorplanung
        sich dazwischenschiebt.
        """
        from candyconc.candyconc_copilot.recipe_runtime import preplan_with_contract

        calls, zusatz = preplan_with_contract(
            "exploration_meta", "Welche Muster fallen auf?", None,
            available_tools=self.WERKZEUGE + ("metadata_values", "semantic_search"),
            gated_tools={},
            contract_tools=["semantic_search"],
        )
        self.assertEqual(calls, [])
        self.assertEqual(zusatz, [])

    def test_kontrakt_mit_passendem_werkzeug_bleibt_unberuehrt(self):
        calls, zusatz = self._plan(["query_count", "frequency_list"])
        self.assertEqual(self._namen(calls), ["query_count"])
        self.assertEqual(zusatz, [])

    def test_ohne_kontrakt_gilt_der_vorplan(self):
        calls, zusatz = self._plan(None)
        self.assertEqual(self._namen(calls), ["query_count"])
        self.assertEqual(zusatz, [])

    def test_capability_gate_bleibt_bindend(self):
        from candyconc.candyconc_copilot.recipe_runtime import preplan_with_contract

        calls, zusatz = preplan_with_contract(
            "frequenz", self.FRAGE, None,
            available_tools=self.WERKZEUGE,
            gated_tools={"query_count": "gesperrt"},
            contract_tools=[],
        )
        self.assertNotIn("query_count", self._namen(calls))


class ZahlenBleibenUnangetastet(unittest.TestCase):
    """H11.6: die Zahl-Dubletten-Regel ist ZURUECKGENOMMEN.

    Sie sollte die Renderer-Dublette ``4781 4.513 VERB`` aufraeumen, konnte
    diese aber nicht von legitimen Paaren unterscheiden. Gemessen wurde,
    dass sie aus einer richtigen Rate eine FALSCHE machte -- die Politur
    fabrizierte damit selbst, wogegen der Harness gebaut ist, und der
    Verlust blieb unter der Meldeschwelle von _log_politur_verlust.

    Eine sichtbare Doppelung ist die richtige Seite des Fehlers: der Leser
    stutzt bei zwei Zahlen, statt eine falsche zu glauben.
    """

    def test_zahl_und_rate_bleiben(self):
        text = "Die Rate liegt bei 32 569,5 pmw."
        self.assertEqual(final_answer_polish(text)[0], text)

    def test_zahl_und_prozent_bleiben(self):
        text = "NOUN 9740 17,3 % aller Tokens."
        self.assertEqual(final_answer_polish(text)[0], text)

    def test_jahr_und_anzahl_bleiben(self):
        text = "Im Jahr 2020 1.234 Belege gefunden."
        self.assertEqual(final_answer_polish(text)[0], text)

    def test_rang_und_anzahl_bleiben(self):
        text = "Auf Rang 1 12.345 Treffer verzeichnet."
        self.assertEqual(final_answer_polish(text)[0], text)

    def test_renderer_dublette_bleibt_sichtbar(self):
        """Bewusst NICHT repariert: sichtbar ist besser als falsch."""
        text = "- 4781 4.513 VERB (85.084,8 80315.4 pmw)"
        self.assertEqual(final_answer_polish(text)[0], text)


if __name__ == "__main__":
    unittest.main()
