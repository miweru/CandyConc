"""Deutungspfad, Baustein 1 (findings/48): der frische Deutungs-Call.

Verhalten, das zählt:
- Der Call schreibt die Antwort und die Deutung bleibt im Text.
- Referenzen löst die Mechanik auf; eine erfundene Zahl überlebt ihren
  Satz nicht (strike + drop), ein Modellausfall landet leer (fail-closed
  über den Salvage-Fallback der Finalisierung).
- Das Evidenz-Paket ist deterministisch und kurz genug für einen Call.

Der Orchestrator kommt über den _real_copilot-Loader (siehe
tests/backend/test_intermediate_stage_recording.py, Docstring).
"""
import asyncio
import os
import unittest

import pytest

from tests.ai import _real_copilot


@pytest.fixture(autouse=True)
def _mechanismen_der_fruheren_vorgabe(monkeypatch):
    """Diese Proben pruefen Streichstufe, Elementdeckel und Paketform.

    Seit dem 2026-09-26 ist der abgenommene Weg Vorgabe:
    Zahlen werden aufgeschrieben statt gestrichen, das Paket sagt die
    Wahrheit ueber sich und ist knapp. Die Mechanismen bleiben zuschaltbar
    und werden hier mit ihren Schaltern geprueft. Die neue Vorgabe prueft
    test_default_is_the_evaluated_path.
    """
    monkeypatch.setenv("CANDYCONC_ZAHLEN_STREICHEN", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "0")
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "0")

ReActOrchestrator = _real_copilot.orchestrator.ReActOrchestrator
_RunTurnState = _real_copilot.orchestrator._RunTurnState
from candyconc.candyconc_copilot.recipe_runtime import politur_mit_zitatwache
from candyconc.candyconc_copilot.interpretation_synthesis import (
    MAX_ABSCHNITTE,
    MAX_ITEMS,
    gutachten_abschnitt_messages,
    deutungspfad_aktiv,
    deutungs_synthese_messages,
    evidenz_paket_text,
    fuehre_gutachten_aus,
    fuehre_deutungs_synthese_aus as deutungs_synthese,
    gutachten_aktiv,
    gutachten_gesamt_messages,
    gutachten_gliederung_messages,
    _parse_gliederung,
)

_EVIDENZ = {
    "id": "ev1",
    "tool": "frequency_list",
    "tool_call_id": "call_1",
    "query": "Klima",
    "status": "success",
    "truncated": False,
    "grounding_truncated": False,
    "grounding_surface": ["Frequenz von „Klima“: 42 Treffer (0,75 pmw)"],
    "fact_surface": {"treffer": 42},
}


def _orchestrator(antwort: str, fehler: bool = False):
    async def _call_llm(messages, exposed_tools, **kwargs):
        if fehler:
            raise RuntimeError("Transport weg")
        assert exposed_tools == [], "Der Deutungs-Call bekommt keine Werkzeuge."
        return {"choices": [{"message": {"content": antwort}}]}

    async def _dispatch(tool_call, _token=None):
        raise AssertionError("kein Tool-Call erwartet")

    orch = ReActOrchestrator([], _call_llm, _dispatch)
    orch._emit_output = lambda bus, event: None
    orch._turn_evidence_items = [dict(_EVIDENZ)]
    return orch


def _turn_state(frage: str):
    ts = _RunTurnState()
    ts.question = frage
    ts.normalized_question = frage
    ts.role = "user"
    ts.llm_is_async = True
    ts.accepts_stream = False
    ts.accepts_json_schema = False
    ts.accepts_tool_choice = False
    ts.forced_next_tools = []
    ts.llm_calls_used = 0
    ts.principal = None
    ts.system_prompt = ""
    return ts


class TestDeutungsSynthese(unittest.IsolatedAsyncioTestCase):
    async def test_deutung_bleibt_referenz_wird_aufgeloest(self):
        antwort = (
            "„Klima“ ist mit 42 Treffern {{ev:ev1}} auffällig frequentiert. "
            "Diese Dichte deutet auf eine thematische Zentralität des "
            "Klimadiskurses im Korpus hin."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("Wie häufig ist „Klima“?"), object(),
            [dict(_EVIDENZ)],
        )
        self.assertIn("thematische Zentralität", text, "Deutung muss bleiben.")
        self.assertIn("42", text, "Die belegte Zahl bleibt.")
        self.assertNotIn("{{ev:ev1}}", text, "Referenzen sind aufgelöst.")

    async def test_erfundene_zahl_ueberlebt_ihren_satz_nicht(self):
        antwort = (
            "„Klima“ ist mit 42 Treffern {{ev:ev1}} auffällig frequentiert. "
            "Insgesamt sind es 999 Treffer, was auf eine explosionsartige "
            "Zunahme deutet."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("Wie häufig ist „Klima“?"), object(),
            [dict(_EVIDENZ)],
        )
        self.assertNotIn(
            "sind es 999", text, "Die Fabrikation darf nicht ungestraft bleiben."
        )
        self.assertIn("[Beleg fehlt]", text, "Ehrlicher Platzhalter statt der Zahl.")
        self.assertIn("42", text)

    async def test_modellausfall_landet_leer(self):
        orch = _orchestrator("", fehler=True)
        text = await deutungs_synthese(
            orch, _turn_state("Wie häufig?"), object(),
            [dict(_EVIDENZ)],
        )
        self.assertEqual(text, "", "Fail-closed: leerer Text, Salvage greift.")


class TestEvidenzPaket(unittest.TestCase):
    def test_rendering_ist_deterministisch_und_vollstaendig(self):
        paket = evidenz_paket_text([dict(_EVIDENZ)])
        self.assertIn("[ev1] frequency_list", paket)
        self.assertIn("Frequenz von „Klima“", paket)
        self.assertEqual(paket, evidenz_paket_text([dict(_EVIDENZ)]))

    def test_item_deckel(self):
        viele = []
        for i in range(MAX_ITEMS + 10):
            item = dict(_EVIDENZ)
            item["id"] = f"ev{i}"
            viele.append(item)
        paket = evidenz_paket_text(viele)
        self.assertIn("[ev0]", paket)
        self.assertNotIn(f"[ev{MAX_ITEMS}]", paket, "Mehr als MAX_ITEMS darf nicht kommen.")

    def test_meldungen_tragen_frage_und_auftrag(self):
        system, user = deutungs_synthese_messages("Wie häufig?", "[ev1] x")
        self.assertIn("FINALE ANTWORT", system["content"])
        self.assertIn("Deutung", system["content"])
        self.assertIn("Werkzeuge", system["content"])
        self.assertIn("Wie häufig?", user["content"])

    def test_absenz_regel_in_beiden_calls(self):
        """F-66-Nachtrag: Absenz-Behauptungen nur nach Paket-Prüfung (F4-Befund)."""
        system, _ = deutungs_synthese_messages("F", "[ev1] x")
        self.assertIn("ABSENZ-REGEL", system["content"])
        g_system, _ = gutachten_abschnitt_messages("F", 1, "T", "A", "[ev1] x")
        self.assertIn("ABSENZ-REGEL", g_system["content"])

    def test_teilkonto_negativ_befund_im_gesamt_call(self):
        """M33-Befund: der Gesamt-Re-Write erfindet Inventare. Der
        Gesamt-Call muss die Teilkonto-Pflicht tragen: jede Teilkonto-Frage
        nur mit den vorhandenen Zahlen, fehlende Datenlage als Negativ-Befund."""
        g_system, _ = gutachten_gesamt_messages("F", ["Absatz"])
        self.assertIn("TEILKONTO-PFLICHT", g_system["content"])
        self.assertIn("Negativ-Befund", g_system["content"])


class TestFlag(unittest.TestCase):
    def test_flag_standard_an(self):
        """Seit dem 2026-09-26 Vorgabe, abschaltbar mit 0."""
        alter = os.environ.pop("CANDYCONC_DEUTUNGSPFAD", None)
        try:
            self.assertTrue(deutungspfad_aktiv())
            os.environ["CANDYCONC_DEUTUNGSPFAD"] = "0"
            self.assertFalse(deutungspfad_aktiv())
        finally:
            if alter is None:
                os.environ.pop("CANDYCONC_DEUTUNGSPFAD", None)
            else:
                os.environ["CANDYCONC_DEUTUNGSPFAD"] = alter

    def test_gutachten_flag_standard_aus(self):
        alter = os.environ.pop("CANDYCONC_GUTACHTEN", None)
        try:
            self.assertFalse(gutachten_aktiv())
            os.environ["CANDYCONC_GUTACHTEN"] = "1"
            self.assertTrue(gutachten_aktiv())
        finally:
            if alter is None:
                os.environ.pop("CANDYCONC_GUTACHTEN", None)
            else:
                os.environ["CANDYCONC_GUTACHTEN"] = alter


_GLIEDERUNG = (
    "## Kernbefund\n"
    "Beantwortet die Frage direkt mit den Keyness-Zahlen {{ev:ev1}}.\n"
    "## Grenzen\n"
    "Benennt, was die Evidenz nicht hergibt {{ev:ev1}}.\n"
)


class _GutachtenFake:
    """Antwortet je Call-Art anders und protokolliert die Reihenfolge."""

    def __init__(self):
        self.arten = []

    async def _call_llm(self, messages, exposed_tools, **kwargs):
        assert exposed_tools == []
        user = str(messages[-1]["content"])
        system = str(messages[0]["content"])
        if "Erstelle 4 bis 8 Abschnitte" in system:
            self.arten.append("gliederung")
            return {"choices": [{"message": {"content": _GLIEDERUNG}}]}
        if "schreibst Abschnitt" in system:
            self.arten.append("abschnitt")
            nr = "1" if "Abschnitt 1 " in system else "2"
            zahl = (
                "Die Frequenz von „word“ liegt bei 42 Treffern {{ev:ev1}}, "
                "das deutet auf eine Schreibungsklasse hin."
                if nr == "1"
                else "Die Evidenz sagt nichts über Stil in easy_language."
            )
            return {"choices": [{"message": {"content": "Absatz zu " + nr + ": " + zahl}}]}
        if "verbindest die vorliegenden Abschnitte" in system:
            self.arten.append("gesamt")
            # Der echte Vertrag: der Gesamt-Call ändert keine Zahl. Der
            # Guard des Orchestrators hängt HINTER der Nutzernachricht,
            # also die Abschnitte-Message gezielt suchen.
            user = next(
                str(m["content"]) for m in messages if "ABSCHNITTE:" in str(m.get("content", ""))
            )
            behalten = [z for z in user.splitlines() if "Treffer" in z or "Grenzen" in z]
            return {"choices": [{"message": {"content":
                "GUTACHTEN-TEXT: " + " | ".join(behalten)}}]}
        raise AssertionError("unbekannter Call: " + user[:80])


class TestGutachten(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_gliedert_schreibt_verbindet(self):
        fake = _GutachtenFake()
        orch = ReActOrchestrator([], fake._call_llm, _nicht_gerufen)
        orch._emit_output = lambda bus, event: None
        orch._turn_evidence_items = [dict(_EVIDENZ)]
        text = await fuehre_gutachten_aus(
            orch, _turn_state("Gutachten zur Frage."), object(),
            [dict(_EVIDENZ)],
        )
        self.assertEqual(fake.arten, ["gliederung", "abschnitt", "abschnitt", "gesamt"])
        self.assertIn("GUTACHTEN-TEXT", text)
        self.assertIn("42", text, "Belegte Zahlen aus Abschnitten bleiben.")

    async def test_erfundene_abschnittszahl_wird_gestrichen(self):
        class _Fake(_GutachtenFake):
            async def _call_llm(self, messages, exposed_tools, **kwargs):
                system = str(messages[0]["content"])
                if "schreibst Abschnitt" in system:
                    return {"choices": [{"message": {"content":
                        "Alles deutet auf 777 Treffer hin, was enorm ist."}}]}
                return await super()._call_llm(messages, exposed_tools, **kwargs)

        fake = _Fake()
        orch = ReActOrchestrator([], fake._call_llm, _nicht_gerufen)
        orch._emit_output = lambda bus, event: None
        orch._turn_evidence_items = [dict(_EVIDENZ)]
        text = await fuehre_gutachten_aus(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertNotIn("777 Treffer", text, "Fabrikation darf nicht landen.")

    async def test_unparsbare_gliederung_wird_einmal_wiederholt(self):
        """Messung 25b: der Gliederungs-Call variiert je Lauf — ein
        unparsbares Erstergebnis bekommt GENAU EINEN Retry, bevor der
        Fallback zur einfachen Synthese greift."""
        fake = _GutachtenFake()
        ursprung = fake._call_llm
        aufrufe = {"gliederung": 0}

        async def _call_llm(messages, exposed_tools, **kwargs):
            system = str(messages[0]["content"])
            if "Erstelle 4 bis 8 Abschnitte" in system:
                aufrufe["gliederung"] += 1
                if aufrufe["gliederung"] == 1:
                    return {"choices": [{"message": {
                        "role": "assistant",
                        "content": "Ich brauche mehr Kontext."}}]}
            return await ursprung(messages, exposed_tools, **kwargs)

        orch = ReActOrchestrator([], _call_llm, _nicht_gerufen)
        orch._emit_output = lambda bus, event: None
        orch._turn_evidence_items = [dict(_EVIDENZ)]
        text = await fuehre_gutachten_aus(
            orch, _turn_state("Gutachten zur Frage."), object(),
            [dict(_EVIDENZ)],
        )
        self.assertEqual(aufrufe["gliederung"], 2,
                         "Der Retry muss genau einmal fahren.")
        self.assertIn("GUTACHTEN-TEXT", text,
                      "Nach dem Retry läuft der Gutachten-Pfad normal.")

    async def test_leere_gliederung_faellt_zum_einzelcall_zurueck(self):
        async def _call_llm(messages, exposed_tools, **kwargs):
            return {"choices": [{"message": {"content": "Direkte Antwort {{ev:ev1}}."}}]}

        orch = ReActOrchestrator([], _call_llm, _nicht_gerufen)
        orch._emit_output = lambda bus, event: None
        orch._turn_evidence_items = [dict(_EVIDENZ)]
        text = await fuehre_gutachten_aus(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertIn("Direkte Antwort", text)


class TestGliederungParse(unittest.TestCase):
    def test_parst_titel_und_auftrag(self):
        abschnitte = _parse_gliederung(_GLIEDERUNG)
        self.assertEqual([t for t, _ in abschnitte], ["Kernbefund", "Grenzen"])
        self.assertIn("Keyness-Zahlen", abschnitte[0][1])

    def test_cap_bei_ueberlauf(self):
        viele = "".join("## A" + str(i) + "\nSatz.\n" for i in range(MAX_ABSCHNITTE + 5))
        self.assertEqual(len(_parse_gliederung(viele)), MAX_ABSCHNITTE)

    def test_leerer_text_keine_abschnitte(self):
        self.assertEqual(_parse_gliederung(""), [])
        self.assertEqual(_parse_gliederung("nur Prosa ohne Kopfzeilen"), [])


async def _nicht_gerufen(tool_call, _token=None):
    raise AssertionError("kein Tool-Call erwartet")


class TestRegelumkehr(unittest.IsolatedAsyncioTestCase):
    """Diagnose 2026-09-04: die Wache traf zielsicher das Lieferstueck.

    Ein vorgeschlagener druckbarer Satz in Anfuehrungszeichen ist eigene
    Stimme, keine Fundstellenbehauptung — er bleibt. Gefallen ist nur der
    Satz, der Evidenz behauptet, die es nicht gibt. Und der Anhang ist
    GENAU EINE Sammelzeile je Antwort, nicht eine je Abschnitt.
    """

    async def test_formulierungsvorschlag_und_satz_bleiben(self):
        antwort = (
            "Der Befund traegt einen druckbaren Satz: „Menschliche und "
            "maschinelle Texte sind nicht durch ein eindeutiges Merkmal "
            "voneinander zu unterscheiden.“ Er beruht auf 42 Treffern "
            "{{ev:ev1}}, daneben stand 999 zu Buche."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertIn("druckbaren Satz", text, "Das Lieferstueck bleibt.")
        self.assertIn("maschinelle Texte sind nicht", text, "Zitat bleibt.")
        self.assertIn("42", text)
        self.assertNotIn("999 zu Buche", text, "Unbelegte Zahl wird markiert.")
        self.assertIn("[Beleg fehlt]", text)
        self.assertLessEqual(text.count("Hinweis:"), 2, "Höchstens zwei Kategorien: Zahlen-Sammelzeile und Zitat-Hinweis.")

    async def test_unresolvierte_referenz_laesst_satz_fallen(self):
        antwort = (
            "Der Befund traegt 42 Treffer {{ev:ev1}}. Laut {{ev:ev99}} sind "
            "es neunzig Prozent. Das ist der Rest der Antwort."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertNotIn("neunzig Prozent", text, "Erfundene Evidenz faellt.")
        self.assertIn("Rest der Antwort", text, "Der uebrige Text bleibt.")

    def test_zitatwache_ankerungsmodus_und_altpfad(self):
        text = (
            "Ein Vorschlag: „Menschliche und maschinelle Texte sind nicht "
            "durch ein eindeutiges Merkmal voneinander zu unterscheiden.“"
        )
        belege = ["Frequenz von „Klima“: 42 Treffer (0,75 pmw)"]
        neu, _ = politur_mit_zitatwache(
            text, [], eigene_zitate_bleiben=True, frage="F.")
        self.assertIn("maschinelle Texte sind nicht", neu,
                      "Im Ankerungsmodus bleibt der Vorschlag.")
        alt, entfernte = politur_mit_zitatwache(text, [], frage="F.")
        self.assertNotIn("maschinelle Texte sind nicht", alt,
                         "Altpfad unverändert: Wache streicht weiterhin.")




class TestBelegChips(unittest.IsolatedAsyncioTestCase):
    """Beleg-Chips: der Modeltext traegt klickbare Referenzen ins Tool."""

    async def test_valide_marke_wird_chip_unbekannte_faellt(self):
        antwort = (
            "42 Treffer {{ev:ev1}} in den Daten. Laut {{ev:evX}} steigt es. "
            "Rest der Deutung."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertIn("[[beleg:ev1]]", text, "Die Chip-Marke muss ueberleben.")
        self.assertNotIn("steigt es", text, "Unbekannte ID: Satz faellt.")
        self.assertIn("Rest der Deutung", text)

    async def test_belegkarte_wird_publiziert(self):
        class _Bus:
            def __init__(self):
                self.events = []

            def publish(self, event, session_id=""):
                self.events.append(event)

        bus = _Bus()
        orch = _orchestrator("Antwort mit {{ev:ev1}}.")
        text = await deutungs_synthese(orch, _turn_state("F."), bus, [dict(_EVIDENZ)])
        grounding = [e for e in bus.events if e.get("event") == "copilot.grounding"]
        self.assertTrue(grounding, "Belegkarte fehlt im Ereignisstrom.")
        eintraege = grounding[-1]["grounding"]["evidence"]
        self.assertEqual(eintraege[0]["id"], "ev1")
        self.assertEqual(eintraege[0]["query"], "Klima")
        self.assertIn("[[beleg:ev1]]", text)




class TestF66EvidenzErzwung(unittest.TestCase):
    """F-66: ohne jede Tool-Evidenz wird der Deutungspfalft nicht
    finalisiert — der Kontrakt meldet stattdessen Pflicht-Werkzeuge, und
    der bestehende Retry-Flow sammelt erst Daten. Ohne den Fix ist die
    Probe rot: die Methode lieferte immer leer."""

    def _contract(self, kind):
        from candyconc.candyconc_copilot.analysis_grounding import AnalysisContract
        return AnalysisContract(deliverable_kind=kind)

    def _orch(self):
        orch = ReActOrchestrator([], None, None)
        orch._turn_evidence_items = []
        return orch

    def test_analyse_ohne_evidenz_fordert_werkzeuge(self):
        os.environ["CANDYCONC_DEUTUNGSPFAD"] = "1"
        try:
            orch = self._orch()
            pending, missing = orch._ra_pending_required_evidence_tools(
                self._contract("analysis_report"), ["frequency_list", "kwic_search"])
            self.assertTrue(pending, "Ohne Evidenz muessen Pflicht-Werkzeuge kommen.")
            self.assertTrue(missing)
        finally:
            os.environ.pop("CANDYCONC_DEUTUNGSPFAD", None)

    def test_lookup_bekommt_keinen_sentinel(self):
        os.environ["CANDYCONC_DEUTUNGSPFAD"] = "1"
        try:
            orch = self._orch()
            _, missing = orch._ra_pending_required_evidence_tools(
                self._contract("lookup_answer"), ["frequency_list"])
            self.assertNotIn(
                "Werkzeug-Evidenz fuer die Deutung", missing,
                "Lookups duerfen den Deutungs-Sentinel nicht bekommen.",
            )
        finally:
            os.environ.pop("CANDYCONC_DEUTUNGSPFAD", None)

    def test_flag_aus_veraendert_nichts(self):
        os.environ["CANDYCONC_DEUTUNGSPFAD"] = "0"
        try:
            orch = self._orch()
            _, missing = orch._ra_pending_required_evidence_tools(
                self._contract("analysis_report"), ["frequency_list"])
            self.assertNotIn(
                "Werkzeug-Evidenz fuer die Deutung", missing,
                "Flag aus: Verhalten unveraendert.",
            )
            orch2 = self._orch()
            orch2._turn_evidence_items = [dict(_EVIDENZ)]
            _, missing2 = orch2._ra_pending_required_evidence_tools(
                self._contract("analysis_report"), ["frequency_list"])
            self.assertNotIn(
                "Werkzeug-Evidenz fuer die Deutung", missing2,
                "Mit Evidenz keine Pflicht-Tools.",
            )
        finally:
            os.environ.pop("CANDYCONC_DEUTUNGSPFAD", None)


class TestF66Vorplan(unittest.TestCase):
    """F-66 am anderen Ende: Kollokationsfragen bekommen ihren
    collocate_stats DETERMINISTISCH in Runde 1 (Freier Modus)."""

    def test_kollokationsfrage_plant_collocate_stats(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            plan_free_mode_first_round,
        )
        plan = plan_free_mode_first_round(
            "Welche Wörter treten neben „Zeit“ typischerweise auf? Deute."
        )
        namen = [c["tool"] for c in plan]
        self.assertIn("collocate_stats", namen, "Kollokation muss vorgeplant sein.")

    def test_zaehlfrage_bleibt_query_count(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            plan_free_mode_first_round,
        )
        plan = plan_free_mode_first_round("Wie häufig kommt „Zeit“ vor?")
        self.assertEqual([c["tool"] for c in plan], ["query_count"])


class TestDeterministischeChips(unittest.IsolatedAsyncioTestCase):
    """Feinjustierung 2026-09-05: Chips kommen DETERMINISTISCH an die
    Paket-Zahlen (a), und Zahlen aus fact_surface gelten als gedeckt (b) —
    ohne die Modell-Referenzierung."""

    async def test_paketzahl_bekommt_chip_ohne_modell_referenz(self):
        antwort = "Es liegen 42 Treffer im Gesamtkorpus vor, das deutet auf ein Randthema."
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertIn("[[beleg:ev1]]", text, "Die Paket-Zahl bekommt ihren Chip.")

    async def test_fact_surface_zahl_gilt_als_gedeckt(self):
        antwort = "Der erwartete Wert liegt bei 2.7210, was zur Einstufung passt."
        evidenz = dict(_EVIDENZ)
        evidenz["grounding_surface"] = ["Frequenz von „Klima“: 42 Treffer"]
        evidenz["fact_surface"] = {"erwartete": 2.7210}
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [evidenz],
        )
        self.assertIn("2.7210", text, "Eine fact_surface-Zahl bleibt stehen.")
        self.assertNotIn(
            "Hinweis: Unbelegte", text,
            "Eine gedeckte Zahl erzeugt keine Streich-Annotation.",
        )


class TestChipUeberlebtIdScrub(unittest.TestCase):
    """Der id_scrub der Politur kappte die Chip-ID (F-66-Nachtrag)."""

    def test_chip_id_ueberlebt_scrub(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            _scrub_internal_ids,
        )
        text = "A 32 [[beleg:E_collocate_stats_1]] Vorkommen."
        self.assertIn(
            "[[beleg:E_collocate_stats_1]]", _scrub_internal_ids(text),
            "Die Chip-ID ist ein Server-Anker, kein Leck.",
        )

    def test_bare_id_wird_weiterhin_gescrubbt(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            _scrub_internal_ids,
        )
        text = "Die Route E_collocate_stats_2 ist intern."
        self.assertNotIn("E_collocate_stats_2", _scrub_internal_ids(text))


class TestAttribution(unittest.IsolatedAsyncioTestCase):
    """F4-Restursache: Wert-Praesenz ist nicht Attribution. Eine Zahl in
    einem Satz ueber Merkmal X muss aus Xs Tabellenzeile stammen."""

    _ROWS = {
        "id": "ev1", "tool": "collocate_stats", "query": "Zeit", "status": "success",
        "grounding_surface": ["Zeit: 11 Kollokate, min_freq 3"],
        "fact_surface": {"min_freq": 3, "rows": [
            {"word": "wird", "logdice": 10.0, "f": 6},
            {"word": "es", "logdice": 8.97, "f": 8},
        ]},
    }

    async def test_fehlzuschreibung_wird_gestrichen(self):
        antwort = "Prompting traegt selbst 5 Beobachtungen, das deutet auf Zufall."
        orch = _orchestrator(antwort)
        evidenz = [dict(self._ROWS)]
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), evidenz,
        )
        self.assertIn("[Beleg fehlt]", text, "Die 5 steht in keiner Prompting-Zeile.")

    async def test_zeilen_attribution_traegt_zahl(self):
        antwort = "wird traegt selbst 6 Beobachtungen, was auf ein haeufiges Praedikat deutet."
        orch = _orchestrator(antwort)
        evidenz = [dict(self._ROWS)]
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), evidenz,
        )
        self.assertIn("6", text, "Die korrekt attribuierte Zeilenzahl bleibt.")
        self.assertNotIn("[Beleg fehlt]", text)


class TestAnkerVerifikationNein(unittest.IsolatedAsyncioTestCase):
    """Regression aus dem Live-Lauf 2026-09-06: der NEIN-Pfad der
    Anker-Verifikation crashte (UnboundLocalError) und riss den Turn mit."""

    async def test_nein_urteil_streicht_zahl_ohne_crash(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        _E = {"id": "ev1", "tool": "collocate_stats", "query": "Zeit",
              "status": "success",
              "grounding_surface": ["Zeit: 11 Kollokate"],
              "fact_surface": {"min_freq": 3,
                               "rows": [{"word": "wird", "logdice": 10.0, "f": 6}]}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: NEIN"}}]}

        orch = Orch()
        text = "Die Aussage: es gibt 10.0 logdice für „wird“, aber keine Daten."
        text_neu, struck = await _anker_verifikation(
            orch, None, None, text, {}, [_E]
        )
        self.assertIn("[Beleg fehlt]", text_neu, "NEIN-Zahl wird markiert.")
        self.assertTrue(struck, "Die gestrichene Zahl wird dokumentiert.")


class TestAnkerVerifikationSubstanz(unittest.IsolatedAsyncioTestCase):
    """F4-Restursache gpt-oss-20b: die modellrobustheit-Fabrikationen
    waren ziffernfreie Universal-Aussagen („Alle untersuchten Modelle …",
    „extreme Chi²-Werte") — der Ziffern-Filter liess sie ungeprueft
    durch, und der Pruefauftrag fragte nur Attribution, nie Substanz."""

    _E = {"id": "ev1", "tool": "collocate_stats", "query": "Kontrast",
          "status": "success",
          "grounding_surface": ["Keyness -> gescheitert"],
          "fact_surface": {"rows": [{"word": "wird", "f": 6}]}}

    async def _verifiziere(self, text, antwort, gesendet):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return await invoker()

            async def _ra_invoke_llm(self, ts, request_messages=None, **kw):
                gesendet.extend(request_messages or [])
                return {"choices": [{"message": {"content": antwort}}]}

        return await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        )

    async def test_universal_ohne_ziffer_wird_markiert(self):
        gesendet: list = []
        text = ("Alle untersuchten Modelle teilen ein sprachliches Profil: "
                "keine systematischen Unterschiede.")
        text_neu, struck = await self._verifiziere(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet, "Ziffernfreie Universal-Aussage wurde nicht geprueft.")
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Universal-Fabrikation wird markiert.")
        self.assertTrue(struck)

    async def test_pruefauftrag_fragt_substanz(self):
        gesendet: list = []
        await self._verifiziere(
            "Alle Modelle zeigen extreme Chi²-Werte.", "A1: JA", gesendet)
        auftrag = " ".join(str(m.get("content", "")) for m in gesendet)
        self.assertIn("substanz", auftrag.casefold(),
                      "Der Pruefauftrag fragt nur Attribution.")
        self.assertIn("keine zeile", auftrag.casefold(),
                      "Der Pruefauftrag nennt die JA-Falle nicht: Ergebnis "
                      "ueber Gegenstaende, fuer die die Tabelle nichts "
                      "enthaelt (Messung 5, Verifier-JA auf Fabrikate).")

    async def test_gedeckte_absenz_bleibt(self):
        gesendet: list = []
        text = "Es liegen keine Messwerte vor; die Abfragen scheitern."
        text_neu, struck = await self._verifiziere(text, "A1: JA", gesendet)
        self.assertTrue(gesendet, "Absenz-Aussage wurde nicht geprueft.")
        self.assertEqual(text_neu, text, "Gedeckte Absenz bleibt unangetastet.")
        self.assertFalse(struck)

    async def test_ausgeschriebene_zahl_wird_geprueft(self):
        """Nachher-Befund 2026-09-08: 'wurden zwölf Generator-Modelle
        analysiert' (die 12 gehoert zum Metadateninventar) lief ohne
        Ziffer am Filter vorbei."""
        gesendet: list = []
        text = "In der Untersuchung wurden zwölf Generator-Modelle analysiert."
        text_neu, struck = await self._verifiziere(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet, "Ausgeschriebene Zahl wurde nicht geprueft.")
        self.assertIn("[Beleg fehlt]", text_neu)

    async def test_weder_noch_absenz_wird_geprueft(self):
        """Nachher-Befund 2026-09-08: 'weder das A-Register noch B sind
        vertreten' bei nur einer belegten Suche lief am Filter vorbei."""
        gesendet: list = []
        text = ("Daraus folgt, dass weder das encyclopedia-Register noch "
                "das news-Register in diesem Datensatz vertreten sind.")
        text_neu, struck = await self._verifiziere(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet, "Weder-noch-Absenz wurde nicht geprueft.")
        self.assertIn("[Beleg fehlt]", text_neu)

    async def test_verifier_ausgang_landet_im_zwischenstand(self):
        """Nachher-Befund 2026-09-08: 0 [Beleg fehlt] ist ununterscheidbar
        von einem stillen Call-Fehler — der Verifier-Ausgang muss
        aufzeichnungsfaehig sein."""
        import os
        import tempfile
        from pathlib import Path
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        verzeichnis = tempfile.mkdtemp()
        self.addCleanup(lambda: os.environ.pop(
            "CANDYCONC_ZWISCHENSTAENDE_DIR", None))
        os.environ["CANDYCONC_ZWISCHENSTAENDE_DIR"] = verzeichnis

        class Orch:
            session = type("S", (), {"session_id": "verif_probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: NEIN"}}]}

        await _anker_verifikation(
            Orch(), None, None, "Alle Modelle teilen ein Profil.", {},
            [dict(self._E)],
        )
        datei = Path(verzeichnis) / "verif_probe" / "4c_anker_verifikation.txt"
        self.assertTrue(
            datei.exists(),
            "Der Verifier-Ausgang wurde nicht aufgezeichnet.",
        )
        self.assertIn("A1", datei.read_text(encoding="utf-8"))


class TestZahlenPflichtAnkerung(unittest.IsolatedAsyncioTestCase):
    """F4-Messung 9 (modellrobustheit): fabrizierte Zahlen (Log-Verhältnis
    9,18, q-Werte < 10⁻⁶⁵) überlebten die Ankerung unmarkiert — die
    Bare-Number-Filterung war großzügiger als die Beleglage. Der
    Zahlen-Pflicht-Sweep markiert JEDE Zahl, die in keiner Belegfläche
    steht; Jahre und Bezeichner-Reste („GPT‑5.5", „404-Fehler") bleiben
    verschont."""

    async def test_fabrizierte_zahl_wird_sichtbar_markiert(self):
        antwort = (
            "Die statistische Signifikanz (q-Werte < 10⁻⁶⁵ bzw. < 10⁻¹⁰⁰) "
            "zeigt Log-Verhältnisse bis zu 9,18 in den Daten."
        )
        orch = _orchestrator(antwort)
        evidenz = [dict(_EVIDENZ)]
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), evidenz,
        )
        self.assertIn("[Beleg fehlt]", text,
                      "Die unbelegte Zahl wird markiert.")

    async def test_bezeichner_und_zitate_bleiben_verschont(self):
        antwort = (
            "Das Modell GPT-5.5 lieferte 18,5 Prozent; seit 2026 bekannt. "
            "Ein 404-Fehler trat auf."
        )
        orch = _orchestrator(antwort)
        evidenz = [dict(_EVIDENZ)]
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), evidenz,
        )
        self.assertIn("GPT-5.5", text, "Bezeichner bleibt heil.")
        self.assertIn("404-Fehler", text, "Status-Codes bleiben heil.")
        self.assertIn("2026", text, "Jahre bleiben heil.")


class TestAbsenzGegenprobe(unittest.IsolatedAsyncioTestCase):
    """F4-Messung 7/8: der Verifier JAs seine eigenen Absenz-Behauptungen
    auch gegen Gegen-Evidenz (Selbst-Verifikations-Grenze). Die
    deterministische Gegenprobe streicht Absenz-Behauptungen über eine
    Analyse-Ebene, deren Zeilen im Paket sichtbar sind — modellunabhängig."""

    _E = {"id": "ev1", "tool": "keyness", "query": "Kontrast",
          "status": "success",
          "grounding_surface": ["Teilkorpus gebildet `model=gpt-5.5`",
                                "Keyness -> 186.483 Zeilen"],
          "fact_surface": {"rows": [{"word": "von", "f": 6}]}}

    async def test_absenz_ueber_sichtbare_ebene_wird_gestrichen(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = ("Eine modellweise Stratifikation fehlt im vorliegenden "
                "Lauf.")
        text_neu, struck = await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        )
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die Absenz wird von der Tabellenzeile widerlegt.")

    async def test_ehrliche_absenz_bleibt_verschont(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        e = {"id": "ev1", "tool": "kwic", "query": "Suche",
             "status": "success",
             "grounding_surface": ["Suche easy_language -> 0 Treffer"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = "Die Suche nach easy_language liefert keine Daten."
        text_neu, struck = await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        )
        self.assertNotIn("[Beleg fehlt]", text_neu,
                         "Ehrliche Absenz mit 0-Treffer-Zeile bleibt.")


class TestAbsenzNachlauf(unittest.IsolatedAsyncioTestCase):
    """F4-Messung 7 (4c-Aufzeichnung): der gebündelte Einzeldurchlauf
    liess Absenz-Widersprüche durch — „Eine modellweise Stratifikation
    fehlt im vorliegenden Lauf" bekam JA, obwohl die Tabellen modellweise
    Teilkorpora zeigen. Absenz-Sätze bekommen einen zweiten, fokussierten
    Durchgang."""

    _E = {"id": "ev1", "tool": "kwic", "query": "Kontrast",
          "status": "success",
          "grounding_surface": ["Teilkorpus gebildet model=gpt-5.5",
                                "Keyness -> 186.483 Zeilen"],
          "fact_surface": {"rows": [{"word": "von", "f": 6}]}}

    async def test_absenz_widerspruch_wird_im_nachlauf_gestrichen(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        rufe = []

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return await invoker()

            async def _ra_invoke_llm(self, ts, request_messages=None, **kw):
                auftrag = str((request_messages or [{}])[0].get("content", ""))
                rufe.append(auftrag)
                if "ABSENZ" in auftrag:
                    inhalt = "B1: NEIN"
                else:
                    inhalt = "A1: JA"
                return {"choices": [{"message": {"content": inhalt}}]}

        text = "Eine modellweise Stratifikation fehlt im vorliegenden Lauf."
        text_neu, struck = await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        )
        self.assertEqual(len(rufe), 2, "Der Absenz-Nachlauf muss fahren.")
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die widerlegte Absenz wird markiert.")
        self.assertTrue(struck)

    async def test_bestaetigte_absenz_bleibt(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        # Keine Gegen-Evidenz im Paket (nur eine ehrliche 0-Treffer-Zeile):
        # ein JA des Verifiers laesst die Absenz stehen.
        e = {"id": "ev1", "tool": "kwic", "query": "Suche",
             "status": "success",
             "grounding_surface": ["Suche easy_language -> 0 Treffer"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = "Eine modellweise Stratifikation fehlt im vorliegenden Lauf."
        text_neu, struck = await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        )
        self.assertNotIn("[Beleg fehlt]", text_neu,
                         "Bestätigte Absenz bleibt stehen.")
        self.assertFalse(struck)


class TestPaketSubstanzVorSkalaren(unittest.TestCase):
    """F4-Messung 14 (4d-Aufzeichnung): die Absenz „keine modellstratifizierte
    Keyness-Tabelle" war im Prüfsatz, aber die Gegen-Evidenz-Zeile
    („Keyness: Richtung gpt_5_5_texts …") lag hinter der Zeilen-Kappe des
    Pakets — die Skalare (status/total/query) verdrängten die Substanz."""

    def test_substantielle_zeile_ueberlebt_die_paket_kappe(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            MAX_ZEILEN_JE_ITEM,
            evidenz_paket_text,
        )
        flaeche = [f"skalar_{i}=x" for i in range(MAX_ZEILEN_JE_ITEM)]
        flaeche.append(
            "Keyness: Richtung gpt_5_5_texts gegen human_texts, "
            "186.483 zurückgegebene Ergebniszeilen"
        )
        item = {"id": "ev9", "tool": "keyness", "query": "KI",
                "status": "success", "grounding_surface": flaeche,
                "fact_surface": {}}
        paket = evidenz_paket_text([item])
        self.assertIn("Richtung gpt_5_5_texts", paket,
                      "Die Gegen-Evidenz-Zeile darf der Kappe zum Opfer "
                      "fallen, solange Skalare sie verdrängen.")


class TestFehlerstatusKlasse(unittest.TestCase):
    """F4-Messung 16: das Modell behauptete „404-Fehler“, während die
    Beleglage status=400 zeigt. Zwei Hebel: (a) das Fehlerprotokoll nennt
    den tatsächlichen HTTP-Status, (b) die Gegenprobe streicht die
    widersprechende Kodenzahl modellunabhängig."""

    def test_fehlerprotokoll_nennt_den_tatsaechlichen_status(self):
        from candyconc.candyconc_copilot.experiment_log import (
            experimente,
        )
        evidenz = [{
            "id": "ev1", "tool": "run_cqlf_query", "status": "error",
            "query": "Schule",
            "fact_surface": {"message": (
                'MCP Fehler: {"type":"about:blank",'
                '"title":"Bad Request","status":400,'
                '"detail":"CQL Parse Fehler: expected RBRACK"}')},
        }]
        zeilen = experimente(evidenz)
        text = "\n".join(zeilen)
        self.assertIn("HTTP 400", text,
                      "Der tatsächliche Status gehört ins Protokoll.")

    async def test_falsche_kodenzahl_wird_gegenprobt(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        e = {"id": "ev1", "tool": "run_cqlf_query", "query": "Schule",
             "status": "error",
             "grounding_surface": ["gescheitert: HTTP 400 — CQL Parse "
                                   "Fehler"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = "Jede Abfrage endete mit dem Fehlerstatus 404."
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die falsche Kodenzahl wird markiert.")
        self.assertTrue(struck)


class TestSammelzeileZaehlt(unittest.TestCase):
    """M25/M26-Urteilerbefund: bei vielen Markern bricht die Aufzählung
    den Lesefluss — ab 7 Markern zählt die Sammelzeile statt aufzulisten."""

    def test_viele_marker_werden_gezaehlt(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _sammelhinweis,
        )
        struck = [f"zahl_{i}" for i in range(1, 9)]
        hinweis = _sammelhinweis(struck)
        self.assertIn("8 Stellen", hinweis,
                      "Die Gesamtzahl wird genannt, nicht einzeln.")
        self.assertNotIn("zahl_7", hinweis,
                         "Die Einzelaufzählung ist gekappt.")

    def test_wenige_marker_werden_gelistet(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _sammelhinweis,
        )
        hinweis = _sammelhinweis(["3", "7"])
        self.assertIn("(3, 7)", hinweis,
                      "Wenige Marker werden einzeln aufgelistet.")


class TestSammelzaehlungAusFinaltext(unittest.TestCase):
    """Messung-23-Diagnoselauf: die Sammelzeile meldete „42 Stellen“,
    der Endtext zeigte 2 — die Abschnitts-Marken überleben den Gesamt-
    Re-Write selten. Die Zählung kommt aus dem ENDTEXT."""

    def test_zaehlung_zaehlt_endtext_marker(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _sammelhinweis_aus_finaltext,
        )
        final = ("Der Befund ist [Beleg fehlt] und bleibt [Beleg fehlt] "
                 "bestehen.")
        hinweis = _sammelhinweis_aus_finaltext(final)
        self.assertIn("2 Stellen", hinweis, hinweis)
        self.assertIn("[Beleg fehlt]", hinweis)

    def test_ohne_marker_kein_hinweis(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _sammelhinweis_aus_finaltext,
        )
        self.assertEqual(
            _sammelhinweis_aus_finaltext("Ein sauberer Befund."), "")


class TestExperimentScope(unittest.TestCase):
    """F4-Messung 23: „Trefferzahl … → 45.334 Treffer" ohne Korpus-Scope
    liess die Modell-Ableitung (2852,10 pro Mio.) am falschen Nenner
    nicht prüfbar zu — der Docset-Scope gehört in die Zeile."""

    def test_ergebnis_zeile_nennt_den_docset_scope(self):
        from candyconc.candyconc_copilot.experiment_log import (
            experimente,
        )
        evidenz = [{
            "id": "ev1", "tool": "query_count", "status": "success",
            "query": '[lemma="sondern"]',
            "fact_surface": {"total": 45334, "docset_id": "gpt_5_5",
                             "rows": []},
        }]
        zeilen = experimente(evidenz)
        text = "\n".join(zeilen)
        self.assertIn("45.334", text)
        self.assertIn("gpt_5_5", text,
                      "Der Docset-Scope gehört in die Experimentzeile.")


class TestKeynessSpitzeMitWerten(unittest.TestCase):
    """F4-Messung 15 (modellrobustheit-Rest): die „stärkste:"-Zeile des
    Experimentprotokolls nannte Terme ohne Werte — das Modell füllte die
    Lücke mit erfundenen Frequenzen (2852,1/Mio, log_ratio 9,18). Die
    Zeile muss die Werte der Keyness-Zeilen selbst tragen."""

    def test_keyness_werte_stehen_in_der_protokollzeile(self):
        from candyconc.candyconc_copilot.experiment_log import (
            experimente,
        )
        evidenz = [{
            "id": "ev1", "tool": "keyness", "status": "success",
            "query": "KI gegen Mensch",
            "fact_surface": {"rows": [
                {"word": "sondern", "per_million": 2852.1,
                 "log_ratio": 9.18, "q_value": 0.0},
                {"word": "ein", "per_million": 10459.5,
                 "log_ratio": 3.2, "q_value": 0.0},
            ]},
        }]
        zeilen = experimente(evidenz)
        text = "\n".join(zeilen)
        self.assertIn("2852.1", text, "Die pm-Wert fehlt im Protokoll.")
        self.assertIn("log_ratio=9.18", text,
                      "Der Log-Ratio fehlt im Protokoll.")
        self.assertIn("q_value=0.0", text, "Der q-Wert fehlt im Protokoll.")


class TestZitattermGegenprobe(unittest.TestCase):
    """F4-Messung 18: die Synthese behauptete „Wer“ (1436,7) und „oft“
    (1000,3) als signifikant gehäuft — beide Terme stehen in keiner
    Belegzeile. Zitierte Terme einer Ergebnis-Behauptung müssen im Paket
    vorkommen, sonst wird der Satz modellunabhängig gestrichen."""

    _E = {"id": "ev1", "tool": "keyness", "query": "KI gegen Mensch",
          "status": "success",
          "grounding_surface": ["stärkste: Bragança, Habsburgo, B.=(\\z"],
          "fact_surface": {}}

    def test_erfundener_zitatterm_wird_gestrichen(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = ("Tokens wie „Wer“ und „oft“ treten signifikant gehäuft "
                "auf.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Der erfundene Zitatterm wird markiert.")
        self.assertTrue(struck)

    def test_substring_im_paket_zaehlt_nicht(self):
        """Messung 19: „oft“ überlebte, weil „Soft-ware“ den Substring
        enthält — Zitatterme brauchen Wortgrenzen im Paket."""
        e = {"id": "ev1", "tool": "keyness", "query": "KI",
             "status": "success",
             "grounding_surface": [
                 "stärkste: Bragança, Habsburgo",
                 "Software: CandyConc Harnisch",
             ],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = "Adverbien wie „oft“ treten gehäuft auf."
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Der Substring „Soft-ware“ deckt „oft“ nicht.")
        self.assertTrue(struck)

    def test_einzelner_fehlender_term_wird_markiert(self):
        """Messung 20: die Alle-oder-keine-Regel liess den Satz stehen,
        weil EIN zitierte Term zufällig im Paket stand — Term-Einzel-
        prüfung markiert nur den fehlenden Term (F6)."""
        e = {"id": "ev1", "tool": "keyness", "query": "KI",
             "status": "success",
             "grounding_surface": ["stärkste: Bragança, Habsburgo"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Konjunktionen wie „Bragança“ und Adverbien wie „oft“ "
                "treten gehäuft auf.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("„Bragança“", text_neu,
                      "Der gedeckte Term bleibt stehen.")
        self.assertIn("„oft“ [Beleg fehlt]", text_neu,
                      "Nur der fehlende Term wird markiert.")

    def test_zeigen_dokumentieren_als_behauptung(self):
        """Messung 21: „Konkordanzen zeigen ... wie „in die Schule gehen""
        und „Kontextzeilen dokumentieren ..." hatten keinen Behauptungs-
        Wort in der Liste und liefen durch."""
        e = {"id": "ev1", "tool": "run_cqlf_query", "query": "Schule",
             "status": "success",
             "grounding_surface": ["Eine technische Schule braucht "
                                   "Labors"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Die verfügbaren Konkordanzen zeigen standardisierte "
                "Referenzierungen wie „in die Schule gehen“.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("„in die Schule gehen“ [Beleg fehlt]", text_neu,
                      "Der unbelegte Zitatterm wird markiert.")

    def test_null_treffer_behauptung_wird_gegenprobt(self):
        """Messung 21: „null Treffer für „Bericht"" — das Paket weist
        Bericht-Treffer aus, die Absenz ist widerlegt."""
        e = {"id": "ev1", "tool": "run_cqlf_query", "query": "Bericht",
             "status": "success",
             "grounding_surface": ['[word="Bericht"] → 12.465 Treffer'],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Die Abfragen lieferten ausschließlich null Treffer für "
                "„Bericht“.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die widerlegte Null-Treffer-Behauptung wird "
                      "markiert.")

    def test_modellgetrennte_absenz_wird_gegenprobt(self):
        """Messung 22: „Ohne modellgetrennte Keyness-Berechnungen“ —
        die Beleglage weist die modellgetrennte Keyness-Richtung aus."""
        e = {"id": "ev1", "tool": "keyness", "query": "Kontrast",
             "status": "success",
             "grounding_surface": ["Keyness: Richtung gpt_5_5_texts "
                                   "gegen human_texts, 186.483 "
                                   "Ergebniszeilen"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Ohne modellgetrennte Keyness-Berechnungen bleibt jede "
                "Aussage zu Ausreißern spekulativ.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die widerlegte Absenz wird markiert.")
        self.assertTrue(struck)

    def test_aggregat_absenz_mit_richtung_zeile(self):
        """Messung 24: „Keyness-Berechnung ausschließlich auf dem
        aggregierten KI-Pool" — das Paket enthält die Richtung-Zeile der
        modellgetrennten Keyness und widerlegt die Absenz."""
        e = {"id": "ev1", "tool": "keyness", "query": "Kontrast",
             "status": "success",
             "grounding_surface": ["Keyness: Richtung gpt_5_5_texts "
                                   "gegen human_texts, 186.483 "
                                   "Ergebniszeilen"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Eine Prüfung bestätigt, dass die Keyness-Berechnung "
                "ausschließlich auf dem aggregierten KI-Pool gegen die "
                "Human-Referenz durchgeführt wurde.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die widerlegte Aggregat-Absenz wird markiert.")
        self.assertTrue(struck)

    def test_inventar_wertelisten_kommen_in_den_anhang(self):
        """Messung 25: das Modell zählt Inventar-Werte auf („dreizehn
        Varianten", „21 Quellen", prompting_method), deren Listen der
        Anhang nicht trug — die Behauptungen blieben unprüfbar."""
        items = [{
            "id": "E_metadata_values_1", "tool": "metadata_values",
            "query": "Inventar", "status": "success",
            "grounding_surface": ["status=success"],
            "fact_surface": {
                "values": {
                    "variant": [f"v{i}" for i in range(1, 14)],
                    "quelle": [f"q{i}" for i in range(1, 22)],
                    "prompting_method": ["a", "b", "c"],
                },
                "value_counts": {"variant": 13, "quelle": 21,
                                 "prompting_method": 3},
            },
        }]
        text = "Das Inventar weist die Felder aus [[beleg:E_metadata_values_1]]."
        poliert, _ = politur_mit_zitatwache(
            text, items, eigene_zitate_bleiben=True)
        self.assertIn("variant", poliert)
        self.assertIn("(+7)", poliert,
                      "Die Kürzung der Werteliste wird gezählt offengelegt.")
        self.assertIn("quelle", poliert,
                      "Die genannten Felder gehören in den Anhang.")

    def test_zitat_mit_satzzeichen_abweichung_bleibt_ungeflaggt(self):
        """Messung 26 (Zitatwache-False-Positive): das Belegzeilen-Zitat
        trug „Aufgaben ?“ (Leerraum vor dem Satzzeichen), das Modellzitat
        „Aufgaben?“ — der exakte Vergleich flaggte es fälschlich."""
        e = {"id": "ev4", "tool": "run_cqlf_query", "query": "Abgeordnete",
             "status": "success",
             "grounding_surface": [
                 'kwic[0] "Wer ist der Bundes-Wahl-Leiter und was sind '
                 'seine Aufgaben ?"'],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _unverifizierte_zitate,
        )
        text = ("Wie der Hinweis sagt: „Wer ist der Bundes-Wahl-Leiter "
                "und was sind seine Aufgaben?“")
        funde = _unverifizierte_zitate(text, [dict(e)])
        self.assertEqual(funde, [],
                         "Das Zitat steht (nach Leerraum-Normalisierung) "
                         "in der Belegzeile.")

    def test_zitat_muss_in_den_element_zeilen_stehen(self):
        """M28b: das erfundene KWIC-Zitat trug einen GÜLTIGEN Chip — der
        Chip deckt das Element, nicht das Zitat. Das zitierte Kontext-
        Fragment muss in den Zeilen des Elements wiederzufinden sein."""
        e = {"id": "ev4", "tool": "run_cqlf_query", "query": "Abgeordnete",
             "status": "success",
             "grounding_surface": [
                 'kwic[0] "Städte haben daher versucht ,"',
                 'kwic[1] "Das kam daher, dass"',
             ],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Ein globaler Kontext lautet „Wissenschaftler sind daher "
                "der Meinung“ [[beleg:ev4]].")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Das erfundene Zitat wird markiert.")
        self.assertTrue(struck)

    def test_wortgetreues_element_zitat_bleibt(self):
        e = {"id": "ev4", "tool": "run_cqlf_query", "query": "Abgeordnete",
             "status": "success",
             "grounding_surface": [
                 'kwic[0] "Städte haben daher versucht ,"'],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        text = ("Ein Kontext lautet „Städte haben daher versucht“ "
                "[[beleg:ev4]].")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertNotIn("[Beleg fehlt]", text_neu,
                         "Das wortgetreue Zitat bleibt belegt.")

    def test_gedeckter_zitatterm_bleibt(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = "Tokens wie „Bragança“ treten gehäuft auf."
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        ))
        self.assertNotIn("[Beleg fehlt]", text_neu,
                         "Der im Paket stehende Term bleibt.")
        self.assertFalse(struck)


class TestBelegzeilenAnhang(unittest.TestCase):
    """F4-Messung 10 (Klasse c): Chips [[beleg:ID]] verweisen auf
    Evidenz-Elemente, deren Zeilen der Auslieferungstext nicht trägt —
    für den Leser nicht prüfbar. Der Anhang „Belegzeilen" listet je
    ZITIERTER ID dessen Zeilen; nicht zitierte Elemente bleiben draußen."""

    _ITEMS = [
        {"id": "ev1", "tool": "keyness", "query": "KI gegen Mensch",
         "status": "success",
         "grounding_surface": ["Keyness -> 186.483 Zeilen",
                               "stärkste: sondern"],
         "fact_surface": {}},
        {"id": "ev2", "tool": "kwic", "query": "nicht zitiert",
         "status": "success",
         "grounding_surface": ["KWIC: 12 Zeilen"], "fact_surface": {}},
    ]

    def test_zitierte_ids_bekommen_ihre_zeilen(self):
        text = "Der Kernbefund steht [[beleg:ev1]] und bleibt."
        poliert, _ = politur_mit_zitatwache(
            text, self._ITEMS, eigene_zitate_bleiben=True)
        self.assertIn("Belegzeilen", poliert, "Der Anhang fehlt.")
        self.assertIn("Keyness -> 186.483 Zeilen", poliert,
                      "Die Zeile des zitierten Elements muss stehen.")
        self.assertNotIn("nicht zitiert", poliert,
                         "Unzitierte Elemente gehören nicht in den Anhang.")

    def test_schreibungs_fussnote_bekommt_anhangszeile(self):
        text = ("Die Zeile „queso“ zählt eine Schreibungsklasse: die 1 "
                "Treffer trägt „Queso“, „queso“ selbst kommt dort nicht "
                "vor.")
        poliert, _ = politur_mit_zitatwache(
            text, [], eigene_zitate_bleiben=True)
        self.assertIn("Belegzeilen", poliert,
                      "Die Fußnote braucht ihre Zeile im Anhang.")
        self.assertIn("Schreibung „queso“", poliert,
                      "Die Zeile muss als Tabellenzeile sichtbar sein.")
        self.assertIn("1 Treffer", poliert)

    def test_fussnote_traegt_selbst_zahl_im_anhang(self):
        """Messung 12: die Fußnote behauptet „selbst 13“ — die Anhangs-
        zeile muss diese Zahl tragen, sonst bleibt sie unbelegt."""
        text = ("Die Zeile „Shift“ zählt eine Schreibungsklasse: von den "
                "27 Treffern trägt „Shift“ selbst 13, die Mehrheit trägt "
                "„Shift“.")
        poliert, _ = politur_mit_zitatwache(
            text, [], eigene_zitate_bleiben=True)
        self.assertIn("Schreibung „Shift“", poliert)
        self.assertRegex(
            poliert, r"Schreibung „Shift“[^\n]*selbst 13",
            "Die eigene Trefferzahl muss in der Anhangszeile stehen.")

    def test_modellspezifische_absenz_wird_gegenprobe(self):
        """Messung 12: „keine modell-spezifischen Keyness-Werte“ widerlegt
        die Gegen-Evidenz „Keyness: Richtung gpt_5_5 gegen …“."""
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )
        e = {"id": "ev1", "tool": "keyness", "query": "Kontrast",
             "status": "success",
             "grounding_surface": ["Keyness: Richtung gpt_5_5 gegen "
                                   "human_texts, 186.483 Zeilen"],
             "fact_surface": {}}

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: JA"}}]}

        text = ("Die Evidenz liefert keine modell-spezifischen "
                "Keyness-Werte.")
        text_neu, struck = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, [dict(e)]
        ))
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die widerlegte Absenz wird markiert.")
        self.assertTrue(struck)

    def test_substantielle_zeilen_schlagen_skalare(self):
        """Messung 13: die Anhangs-Kappe schnitt genau die rows[...]-Zeilen
        weg, weil die Skalare (status/total/query) zuerst kamen."""
        items = [{
            "id": "ev1", "tool": "run_cqlf_query", "query": "Schule",
            "status": "success",
            "grounding_surface": [
                "status=success", "total=11681", "query=Schule",
                'rows[0] {"left": "in der", "kw": "Schule", "right": "lernen"}',
                'rows[1] {"left": "auf der", "kw": "Schule", "right": "schwänzen"}',
            ],
            "fact_surface": {},
        }]
        text = "Der Befund steht [[beleg:ev1]] im Raum."
        poliert, _ = politur_mit_zitatwache(
            text, items, eigene_zitate_bleiben=True)
        self.assertIn("rows[0]", poliert,
                      "Die substantielle Belegzeile muss den Skalaren "
                      "vorgezogen werden.")

    def test_ohne_chips_kein_anhang(self):
        poliert, _ = politur_mit_zitatwache(
            "Ein Text ohne Chips.", self._ITEMS,
            eigene_zitate_bleiben=True)
        self.assertNotIn("Belegzeilen", poliert,
                         "Ohne Chips gibt es nichts zu belegen.")


class TestPoliturRespektiertDeutungsAnkerung(unittest.TestCase):
    """F4-Neumessung 2026-09-08 (zweiter Befund): der Gutachten-Pfad
    markiert unverifizierte Saetze mit dem Platzhalter (F6: markieren,
    nicht streichen) — aber die Endpolitur strich diese Saetze GANZ
    (Renderer-Policy H6 in ``aussagen_ohne_deckung_streichen``), damit
    verschwanden die Markierungen aus der Auslieferung (0
    [Beleg fehlt] trotz 3 NEIN-Urteilen des Verifiers, Text verstuemmelt).
    Der Deutungs-Kontrakt (``eigene_zitate_bleiben``) muss bis in die
    Politur reichen."""

    _TEXT = (
        "**Einleitung**\nDie Daten zeigen ein Signal.\n\n"
        "Die Keyness-Liste liefert Werte weit über dem Schwellenwert.\n\n"
        "[Beleg fehlt]"
    )

    def test_anker_markierung_ueberlebt_die_landung(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            politur_mit_zitatwache,
        )
        poliert, _ = politur_mit_zitatwache(
            self._TEXT, [], eigene_zitate_bleiben=True)
        self.assertIn(
            "[Beleg fehlt]", poliert,
            "Die Anker-Markierung muss die Landung ueberleben (F6).")

    def test_legacy_pfad_streicht_weiter(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            politur_mit_zitatwache,
        )
        poliert, _ = politur_mit_zitatwache(
            self._TEXT, [], eigene_zitate_bleiben=False)
        self.assertNotIn(
            "[Beleg fehlt]", poliert,
            "Der Legacy-Pfad behaelt seine Renderer-Policy (H6).")


class TestVerifikationsFilterLücken(unittest.IsolatedAsyncioTestCase):
    """F4-Messung 5 (2026-09-08, qwen3.6-27b-mtp): drei Lückenklassen, die
    die Verifikation umliefen — ausschliesslich-Universal-Aussagen,
    hochgestellte Zahlen (q-Werte bis 10⁻²⁰⁰) und die Chip-Zeilen-
    Ausnahme (die Chip-Marke belegt nur EINE Zahl, der Rest der Zeile
    blieb ungeprüft)."""

    _E = {"id": "ev1", "tool": "kwic", "query": "Kontrast",
          "status": "success",
          "grounding_surface": ["Kontrast: 331 Treffer"],
          "fact_surface": {"rows": [{"word": "von", "f": 6}]}}

    async def _pruefe(self, text, antwort, gesendet):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return await invoker()

            async def _ra_invoke_llm(self, ts, request_messages=None, **kw):
                gesendet.extend(request_messages or [])
                return {"choices": [{"message": {"content": antwort}}]}

        return await _anker_verifikation(
            Orch(), None, None, text, {}, [dict(self._E)]
        )

    async def test_ausschliesslich_wird_geprueft(self):
        gesendet: list = []
        text = ("Im Kontrast dazu tritt das Muster fast ausschließlich "
                "in einer festen Klammer auf.")
        text_neu, _ = await self._pruefe(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet, "Ausschliesslich-Aussage wurde nicht geprueft.")
        self.assertIn("[Beleg fehlt]", text_neu)

    async def test_hochgestellte_zahl_wird_geprueft(self):
        gesendet: list = []
        text = "Die Trennschärfe ist robust (q-Werte bis 10⁻²⁰⁰)."
        text_neu, _ = await self._pruefe(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet, "Hochgestellte Zahl wurde nicht geprueft.")
        self.assertIn("[Beleg fehlt]", text_neu)

    async def test_chip_zeile_wird_trotzdem_geprueft(self):
        gesendet: list = []
        text = ("Das Signal ist in jedem Register stabil [[beleg:ev1]] "
                "und bleibt über alle Teilkorpora hinweg bestehen.")
        await self._pruefe(text, "A1: NEIN", gesendet)
        self.assertTrue(
            gesendet,
            "Chip-Marke deckt nur EINE Zahl — die Zeile darf nicht "
            "komplett ungeprueft bleiben.")


class TestMessung6Lücken(unittest.TestCase):
    """F4-Messung 6 (2026-09-09): die Zahl-Streichung traf Ziffern in
    Modellnamen („GPT‑5.2" -> „GPT‑5.[Beleg fehlt]"), und das Modell
    schrieb Literal-[[beleg:evX]]-Marker, die ohne Validierung in der
    Auslieferung landeten."""

    def test_bezeichner_bleiben_von_der_nein_streichung_verschont(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            _anker_verifikation,
        )

        class Orch:
            session = type("S", (), {"session_id": "probe"})()

            def _extract_message_content(self, c):
                return c

            async def _ra_call_llm_with_recovery(self, ts, bus, invoker=None):
                return {"choices": [{"message": {"content": "A1: NEIN"}}]}

        text = "GPT‑5.2 erreichte 10,3 Prozent Anteil."
        text_neu, _ = asyncio.run(_anker_verifikation(
            Orch(), None, None, text, {}, []))
        self.assertIn("GPT‑5.2", text_neu,
                      "Der Modellname ist kein Beleg-Mangel.")
        self.assertIn("[Beleg fehlt]", text_neu,
                      "Die unbelegte Prozentzahl wird markiert.")

    def test_mechanische_ankerung_trifft_keine_bezeichner(self):
        from candyconc.candyconc_copilot.recipe_runtime import (
            strike_unbound_numbers,
        )
        text = "Das Modell GPT‑5.2 lieferte 5.2 Prozent der Tokens."
        struck = strike_unbound_numbers(
            text, [{"number": "5.2", "context": ""}], annotate=False)
        self.assertIn("GPT‑5.2", struck,
                      "Der Bezeichner darf nicht wie eine Zahl fallen.")
        self.assertIn("[Beleg fehlt] Prozent", struck,
                      "Die freie Zahl wird markiert.")

    def test_fremder_literal_chip_faellt_mit_satz(self):
        antwort = (
            "Laut [[beleg:ev1]] 42 Treffer. Laut [[beleg:evX]] steigt es. "
            "Rest der Deutung."
        )
        orch = _orchestrator(antwort)
        text = asyncio.run(deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)]))
        self.assertIn("[[beleg:ev1]]", text, "Bekannte Marke bleibt Chip.")
        self.assertNotIn("steigt es", text,
                         "Fremde Literal-Marke: Satz faellt wie bei {{ev:}}.")


class TestQuotePolitik(unittest.IsolatedAsyncioTestCase):
    """F4-Restbefund: Belegzeilen-Imitate in Anfuehrung stehen nicht in der
    Beleglage — sie werden nicht gestrichen (B9), aber ehrlich markiert."""

    async def test_unverifizierbares_zitat_bekommt_hinweis(self):
        antwort = (
            "Belegzeilen: \u201eAbraham ist ein wichtiger Mann im Kontext des Berichts\u201c "
            "und eine zweite Stelle. Die Deutung folgt aus 42 Treffern {{ev:ev1}}."
        )
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertIn("stehen nicht in der Beleglage", text, "Ehrliche Markierung fehlt.")
        self.assertIn("Abraham ist ein wichtiger Mann", text, "B9: Zitat bleibt stehen.")

    async def test_regulaere_antwort_ohne_zitate_bleibt_sauber(self):
        antwort = "Die Antwort: es liegen 42 Treffer {{ev:ev1}} vor, das deutet auf ein Randthema."
        orch = _orchestrator(antwort)
        text = await deutungs_synthese(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertNotIn("Belegzeilen-Imitate", text, "Sauberer Text ohne Zitate bleibt ohne Hinweis.")


class TestEskalationBeiHuelle(unittest.IsolatedAsyncioTestCase):
    """F4 gelernt (modellrobustheit-Rest): eine kurze Huelle ohne Zahlen ist
    kein Kernbefund — GENAU EINE Eskalation, wenn das Paket reich ist."""

    async def test_huelle_loest_eskalation_aus(self):
        from candyconc.candyconc_copilot.interpretation_synthesis import (
            fuehre_gutachten_aus,
        )
        gliederung = "## Kernbefund\nAus der Evidenz {{ev:ev1}} folgt die Antwort.\n"

        class Fake:
            def __init__(self):
                self.eskaliert = False
                self.log = []

            async def _call_llm(self, messages, tools, **kw):
                system = str(messages[0]["content"])
                self.log.append(system[:50])
                if "Erstelle 4 bis 8 Abschnitte" in system:
                    return {"choices": [{"message": {"content": gliederung}}]}
                if "schreibst Abschnitt" in system:
                    return {"choices": [{"message": {"content":
                        "Die vorliegende Befundlage erlaubt keine belastbare Aussage darüber."}}]}
                if "verbindest die vorliegenden Abschnitte" in system:
                    return {"choices": [{"message": {"content":
                        "Die vorliegende Befundlage erlaubt keine belastbare Aussage darüber."}}]}
                self.eskaliert = True
                return {"choices": [{"message": {"content":
                    "Kernbefund: gemini trägt 7141534 Tokens, gpt-5.2 13497564 "
                    "Tokens [[beleg:ev1]] — die Last ist ungleich verteilt."}}]}

        fake = Fake()
        orch = _orchestrator("x")
        orch.call_llm = fake._call_llm  # der Fake TREIBT den Turn
        text = await fuehre_gutachten_aus(
            orch, _turn_state("F."), object(), [dict(_EVIDENZ)],
        )
        self.assertTrue(fake.eskaliert, "Die Huelle muss die Eskalation auslösen.")
        self.assertIn("7141534", text, "Der eskalierte Kernbefund mit Zahlen kommt an.")

if __name__ == "__main__":
    unittest.main()


class TestF4Wachenflag(unittest.IsolatedAsyncioTestCase):
    """Anchor verification follows CANDYCONC_F4_WACHEN.

The default skips _anker_verifikation and preserves the other anchoring
steps. Setting the flag to 1 enables that verification stage."""

    def setUp(self):
        self._alt = os.environ.pop("CANDYCONC_F4_WACHEN", None)

    def tearDown(self):
        os.environ.pop("CANDYCONC_F4_WACHEN", None)
        if self._alt is not None:
            os.environ["CANDYCONC_F4_WACHEN"] = self._alt

    async def _lauf(self):
        from unittest import mock
        from candyconc.candyconc_copilot import interpretation_synthesis as modul

        aufrufe = []

        async def _zaehle(orch, ts, bus, text, zahlen, items):
            aufrufe.append(text)
            return text, []

        antwort = (
            "„Klima“ ist mit 42 Treffern {{ev:ev1}} auffällig frequentiert. "
            "Es gibt keinen Beleg für 999 Treffer, das darfst du nicht drucken."
        )
        with mock.patch.object(modul, "_anker_verifikation", _zaehle):
            text = await deutungs_synthese(
                _orchestrator(antwort), _turn_state("Wie häufig ist „Klima“?"),
                object(), [dict(_EVIDENZ)],
            )
        return text, aufrufe

    async def test_default_laesst_die_pruefstufen_weg_und_ankert_trotzdem(self):
        text, aufrufe = await self._lauf()
        self.assertEqual(aufrufe, [], "Ohne Flag wird keine Pruefstufe gerufen.")
        self.assertIn("42", text, "Die belegte Zahl bleibt.")
        self.assertIn("[Beleg fehlt]", text, "Die erfundene 999 wird weiter markiert.")
        self.assertIn("darfst du nicht drucken", text, "Der Satz mit kein bleibt stehen.")

    async def test_flag_null_bleibt_gleichbedeutend_mit_dem_default(self):
        os.environ["CANDYCONC_F4_WACHEN"] = "0"
        text, aufrufe = await self._lauf()
        self.assertEqual(aufrufe, [], "Mit Flag 0 wird keine Pruefstufe gerufen.")
        self.assertIn("42", text)

    async def test_flag_eins_schaltet_die_pruefstufen_wieder_zu(self):
        os.environ["CANDYCONC_F4_WACHEN"] = "1"
        text, aufrufe = await self._lauf()
        self.assertEqual(len(aufrufe), 1, "Mit Flag 1 laeuft die Anker-Verifikation.")
        self.assertIn("42", text)
