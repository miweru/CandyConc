"""Classifier fallback records why a proposed recipe was rejected.

Its configured emergency ceiling exceeds the reference warm-call duration.
Distinguish an absent classifier result from a result rejected afterward."""

from __future__ import annotations

import asyncio
import unittest

from candyconc.candyconc_copilot import recipe_runtime as rr


class Reissleine(unittest.TestCase):
    """Der Deckel steht weit ueber der gemessenen Arbeit."""

    def test_das_budget_liegt_weit_ueber_dem_gemessenen_call(self):
        gemessen = rr.RECIPE_CLASSIFIER_GEMESSEN_WARM_S
        self.assertGreater(gemessen, 0, "ohne Messwert ist der Deckel Willkuer")
        # Faktor 10 ist die Grenze zwischen Reissleine und Zeitplan. Bei den
        # alten 25 s gegen 16,6 s stand der Faktor auf 1,5, und das Limit
        # griff bei jeder zweiten Frage.
        self.assertGreaterEqual(
            rr.RECIPE_CLASSIFIER_TIMEOUT_S,
            gemessen * 10,
            "Der Deckel ist ein Zeitplan geworden, kein Failsafe. "
            f"gemessen {gemessen} s, Deckel {rr.RECIPE_CLASSIFIER_TIMEOUT_S} s",
        )

    def test_der_effektive_wert_folgt_der_konstante(self):
        self.assertEqual(
            rr.recipe_classifier_timeout_s(), rr.RECIPE_CLASSIFIER_TIMEOUT_S
        )


def _routing(**kw):
    """route_turn_recipe ohne Netz, mit steuerbarem Klassifikator."""

    async def _lauf():
        return await rr.route_turn_recipe(
            kw.pop("frage", "Wo unterscheiden sich die Register?"),
            kw.pop("capabilities", {"routing_tool_universe": ["run_cqlf_query"]}),
            kw.pop("call_llm", None),
            **kw,
        )

    return asyncio.run(_lauf())


class VerwerfungIstSichtbar(unittest.TestCase):
    def setUp(self):
        # Der Klassifikator antwortet ohne Netz immer dasselbe.
        self._echt = rr.classify_recipe_llm

        async def _fake(frage, call_llm, **_kw):
            return self.antwort

        rr.classify_recipe_llm = _fake
        self.addCleanup(setattr, rr, "classify_recipe_llm", self._echt)
        self.antwort = ""

    def test_ein_kernwerkzeug_ausserhalb_des_universums_wird_benannt(self):
        """kontrast braucht keyness. Fehlt es, muss das dastehen."""
        self.antwort = "kontrast"
        ergebnis = _routing(
            call_llm=lambda *a, **k: "",
            capabilities={"routing_tool_universe": ["run_cqlf_query"]},
        )
        grund = ergebnis.get("verworfen", "")
        self.assertIn("kontrast", grund, ergebnis)
        self.assertIn("keyness", grund, ergebnis)

    def test_eine_unbekannte_rezept_id_wird_benannt(self):
        self.antwort = "gibtesnicht"
        ergebnis = _routing(call_llm=lambda *a, **k: "")
        self.assertIn("gibtesnicht", ergebnis.get("verworfen", ""), ergebnis)

    def test_ein_angenommener_pick_traegt_keinen_verwerfungsgrund(self):
        """Sonst waere die Spur Laerm statt Auskunft."""
        self.antwort = "kontrast"
        ergebnis = _routing(
            call_llm=lambda *a, **k: "",
            capabilities={"routing_tool_universe": ["keyness"]},
        )
        self.assertEqual(ergebnis.get("stage"), rr.ROUTING_STAGE_LLM)
        self.assertNotIn("verworfen", ergebnis, ergebnis)

    def test_der_grund_steht_in_der_annotation(self):
        """Die NAHT zum Leser.

        Ein Eval-Lauf liest Antworten, keine Serverlogs. Steht der Grund nur
        im Log, sieht der Lauf ein falsches Rezept ohne Ursache, und genau
        das ist am 2026-08-31 passiert.
        """
        self.antwort = "kontrast"
        ergebnis = _routing(
            call_llm=lambda *a, **k: "",
            capabilities={"routing_tool_universe": ["run_cqlf_query"]},
        )
        note = rr.recipe_routing_annotation(ergebnis).get("note", "")
        self.assertIn("verworfen=", note, note)
        self.assertIn("keyness", note, note)

    def test_ohne_verwerfung_bleibt_die_annotation_wie_bisher(self):
        note = rr.recipe_routing_annotation(
            {"stage": "trigger", "recipe_id": "frequenz"}
        ).get("note", "")
        self.assertEqual(note, "stage=trigger recipe=frequenz")


if __name__ == "__main__":
    unittest.main()
