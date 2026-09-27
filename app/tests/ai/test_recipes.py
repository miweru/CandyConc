"""Golden- und Struktur-Tests der Rezept-Bibliothek (Agent A, Rezept-Harness).

Abgedeckt:

* Struktur: 8 Rezepte, eindeutige ids, Slots vollstaendig (Schritt-Slots und
  ``{platzhalter}`` in Briefing/Schritten sind deklariert), Briefing maximal
  25 Zeilen, 2-4 Leitplanken, Hausstil (keine Semikola, keine
  Gedankenstriche).
* Auswahl-Golden: ``select_recipe`` trifft fuer jede ``beispiel_frage`` das
  eigene Rezept (0 LLM-Calls, rein deterministisch).
* Live-P3-Regression: die Stichprobenfrage mit Seed liefert das Rezept
  ``gebrauch_kwic`` statt einer Ablehnung, auch unter der realen
  Live-Werkzeugmenge.
* Freier Modus: ``None`` fuer Smalltalk, leere Fragen und kaputte
  ``capabilities``-Objekte, niemals eine Exception.
* Capability-Gate: ohne Kernwerkzeug ist das Rezept nicht waehlbar.
* Rendering: ``render_briefing`` ist deterministisch (byte-identisch),
  fuellt bekannte Slots und listet offene Slots.
* Index: ``recipe_index`` hat genau 8 Zeilen, ist stabil nach id sortiert
  und byte-identisch je Aufruf (KV-Cache).
* Fassade: ``analysis_grounding`` re-exportiert die Rezept-API.
"""

from __future__ import annotations

import re
import unittest

from candyconc.candyconc_copilot import analysis_grounding
from candyconc.candyconc_copilot.grounding_contracts import select_recipe
from candyconc.candyconc_copilot.recipes import (
    RECIPES,
    RECIPES_BY_ID,
    get_recipe,
    recipe_index,
    render_briefing,
)

_PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_LIVE_P3_FRAGE = (
    "Zieh eine Zufallsstichprobe von 5 Treffern für 'und' mit Seed 7."
)
_LIVE_P3_TOOLS = ["run_cqlf_query", "query_count", "frequency_list"]

_EXPECTED_IDS = {
    "assoziation",
    "exploration_meta",
    "frequenz",
    "gebrauch_kwic",
    "kontrast",
    "metadaten_struktur",
    "profil",
    "verlauf",
}


class TestRecipeLibraryStructure(unittest.TestCase):
    def test_eight_recipes_with_unique_ids(self) -> None:
        self.assertEqual(len(RECIPES), 8)
        self.assertEqual({recipe.id for recipe in RECIPES}, _EXPECTED_IDS)
        self.assertEqual(len(RECIPES_BY_ID), 8)

    def test_get_recipe_roundtrip(self) -> None:
        for recipe in RECIPES:
            self.assertIs(get_recipe(recipe.id), recipe)
        with self.assertRaises(KeyError):
            get_recipe("gibt_es_nicht")

    def test_slots_vollstaendig(self) -> None:
        """Jeder Schritt-Slot und jeder Platzhalter ist deklariert."""

        for recipe in RECIPES:
            declared = set(recipe.slots)
            with self.subTest(recipe=recipe.id):
                for step in recipe.schritte:
                    for name in step.slots:
                        self.assertIn(name, declared)
                texts = [recipe.briefing]
                texts.extend(step.ziel for step in recipe.schritte)
                texts.extend(step.tool_hinweis for step in recipe.schritte)
                for text in texts:
                    for name in _PLACEHOLDER_PATTERN.findall(text):
                        self.assertIn(name, declared)

    def test_briefing_und_leitplanken_budget(self) -> None:
        for recipe in RECIPES:
            with self.subTest(recipe=recipe.id):
                self.assertLessEqual(
                    len(recipe.briefing.splitlines()), 25
                )
                self.assertGreaterEqual(len(recipe.leitplanken), 2)
                self.assertLessEqual(len(recipe.leitplanken), 4)
                self.assertTrue(recipe.einsatz.strip())
                self.assertTrue(recipe.abbruch_kriterium.strip())
                self.assertTrue(recipe.deliverable.strip())
                self.assertTrue(recipe.beispiel_frage.strip())
                self.assertTrue(recipe.kern_tools)
                self.assertTrue(recipe.schritte)

    def test_hausstil_keine_semikola_keine_gedankenstriche(self) -> None:
        for recipe in RECIPES:
            rendered = render_briefing(recipe)
            with self.subTest(recipe=recipe.id):
                self.assertNotIn("—", rendered)
                self.assertNotIn(",,", rendered)
                for line in rendered.splitlines():
                    self.assertNotIn(";", line)
        index_text = recipe_index()
        self.assertNotIn(";", index_text)
        self.assertNotIn("—", index_text)

    def test_familien_nur_bekannte_analysis_families(self) -> None:
        from candyconc.candyconc_copilot.grounding_schemas import (
            ANALYSIS_FAMILIES,
        )

        for recipe in RECIPES:
            for family in recipe.familien:
                with self.subTest(recipe=recipe.id, family=family):
                    self.assertIn(family, ANALYSIS_FAMILIES)


class TestRecipeSelectionGolden(unittest.TestCase):
    """Auswahl-Heuristik trifft die eigene Beispiel-Frage (je Rezept)."""

    def test_beispiel_frage_trifft_eigenes_rezept(self) -> None:
        for recipe in RECIPES:
            with self.subTest(recipe=recipe.id):
                selected = select_recipe(recipe.beispiel_frage)
                self.assertIsNotNone(selected)
                self.assertEqual(selected.id, recipe.id)

    def test_selection_ist_deterministisch(self) -> None:
        for recipe in RECIPES:
            first = select_recipe(recipe.beispiel_frage)
            second = select_recipe(recipe.beispiel_frage)
            self.assertIs(first, second)


class TestLiveP3SampleRegression(unittest.TestCase):
    """Die Live-P3-Stichprobenfrage bekommt ein Rezept, nie eine Ablehnung."""

    def test_stichprobe_mit_seed_liefert_gebrauch_kwic(self) -> None:
        selected = select_recipe(_LIVE_P3_FRAGE)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "gebrauch_kwic")

    def test_stichprobe_auch_unter_live_werkzeugmenge(self) -> None:
        selected = select_recipe(
            _LIVE_P3_FRAGE,
            {"available_tools": _LIVE_P3_TOOLS},
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "gebrauch_kwic")


class TestFreeModeAndRobustness(unittest.TestCase):
    def test_smalltalk_und_leere_frage_geben_none(self) -> None:
        self.assertIsNone(select_recipe("Danke, das war alles!"))
        self.assertIsNone(select_recipe(""))
        self.assertIsNone(select_recipe("   "))
        self.assertIsNone(select_recipe(None))  # type: ignore[arg-type]

    def test_kaputte_capabilities_werfen_nie(self) -> None:
        self.assertIsNone(select_recipe("Hallo", capabilities=[1, 2, 3]))  # type: ignore[arg-type]
        self.assertIsNone(
            select_recipe("Hallo", {"available_tools": None})
        )
        selected = select_recipe(
            "Wie häufig kommt 'Klimawandel' im Korpus vor, pro Million "
            "Tokens?",
            {"available_tools": None},
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "frequenz")

    def test_capability_gate_blockt_rezept_ohne_kernwerkzeug(self) -> None:
        ohne_trend = {"available_tools": ["run_cqlf_query", "query_count"]}
        selected = select_recipe(
            "Wie entwickelt sich 'Inflation' über die Zeit im Korpus?",
            ohne_trend,
        )
        self.assertIsNone(selected)
        ohne_keyness = {
            "available_tools": [
                "run_cqlf_query",
                "collocate_stats",
                "metadata_values",
                "create_docset",
                "frequency_list",
            ]
        }
        selected = select_recipe(
            "Welche Schlüsselwörter sind typisch für das Teilkorpus "
            "'news' im Vergleich zum Teilkorpus 'chat'?",
            ohne_keyness,
        )
        self.assertNotEqual(
            getattr(selected, "id", None), "kontrast"
        )

    def test_dispersion_frage_geht_zur_frequenz_nicht_assoziation(
        self,
    ) -> None:
        selected = select_recipe(
            "Wie verteilt sich 'Regierung' im Korpus? Berechne die "
            "Dispersion."
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "frequenz")

    def test_offene_korpusfrage_bekommt_exploration(self) -> None:
        selected = select_recipe(
            "Was fällt in diesem Korpus insgesamt auf? Gib mir einen "
            "Überblick."
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "exploration_meta")


class TestH8HoldoutSelectionRegressions(unittest.TestCase):
    """H8-Generalisierungsfunde: die drei Live-Fehlgriffe der Rezeptwahl."""

    def test_sprachstil_charakterisierung_trifft_exploration(self) -> None:
        # hold_offen_stil: lief in den freien Modus (None).
        selected = select_recipe(
            "Charakterisiere den Sprachstil dieses Korpus in drei Punkten."
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "exploration_meta")

    def test_stil_trigger_nur_an_wortgrenzen(self) -> None:
        # 'wort:stil' matcht 'Stil', aber nie 'still'/'stilistisch'.
        selected = select_recipe("Beschreibe den Stil dieses Korpus.")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "exploration_meta")
        self.assertIsNone(
            select_recipe("Warum ist es in diesem Korpus so still?")
        )

    def test_freier_vergleich_trifft_kontrast(self) -> None:
        # hold_kontrast_mensch_ki: lief in den freien Modus (None).
        selected = select_recipe(
            "Vergleiche die Sprache von Menschen und KI in diesem Korpus."
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "kontrast")

    def test_kontrast_schlaegt_metadaten_bei_kontrast_signalen(self) -> None:
        # big_kontrast_mensch_ki: die Metadaten sind hier Achsenquelle,
        # nicht Frageziel. metadaten_struktur gewann faelschlich.
        selected = select_recipe(
            "Was unterscheidet menschliche Texte sprachlich von den "
            "KI-generierten Versionen in diesem Korpus? Wähle die "
            "Kontrastachse anhand der Metadaten."
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "kontrast")

    def test_reine_metadatenfrage_bleibt_korpus_karte(self) -> None:
        # Ohne Kontrast-Signal bleibt die Metadaten-Familie unangetastet.
        for frage in (
            "Aus welcher Quelle stammen die Texte in diesem Korpus und "
            "unter welcher Lizenz stehen sie?",
            "Welche KI-Modelle sind in diesem Korpus vertreten?",
        ):
            with self.subTest(frage=frage):
                selected = select_recipe(frage)
                self.assertIsNotNone(selected)
                self.assertEqual(selected.id, "metadaten_struktur")

    def test_metadaten_kontrast_override_respektiert_capability_gate(
        self,
    ) -> None:
        # Ohne keyness bleibt die ehrliche Korpus-Karte die Antwort.
        selected = select_recipe(
            "Was unterscheidet menschliche Texte sprachlich von den "
            "KI-generierten Versionen in diesem Korpus? Wähle die "
            "Kontrastachse anhand der Metadaten.",
            {"available_tools": ["metadata_values", "query_count"]},
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "metadaten_struktur")


class TestRenderBriefing(unittest.TestCase):
    def test_rendering_ist_byte_identisch(self) -> None:
        for recipe in RECIPES:
            with self.subTest(recipe=recipe.id):
                self.assertEqual(
                    render_briefing(recipe), render_briefing(recipe)
                )
                slots = {name: f"WERT_{name}" for name in recipe.slots}
                self.assertEqual(
                    render_briefing(recipe, slots),
                    render_briefing(recipe, slots),
                )

    def test_rendering_enthaelt_kernbausteine(self) -> None:
        for recipe in RECIPES:
            rendered = render_briefing(recipe)
            with self.subTest(recipe=recipe.id):
                self.assertIn(f"REZEPT {recipe.id}", rendered)
                self.assertIn("Schritte:", rendered)
                self.assertIn("Abbruchkriterium:", rendered)
                self.assertIn("Antwortform:", rendered)
                self.assertIn("Leitplanken:", rendered)
                for leitplanke in recipe.leitplanken:
                    self.assertIn(leitplanke, rendered)

    def test_slots_werden_gefuellt_und_offene_gelistet(self) -> None:
        # Dieselbe Mechanik mit achse und fenster: die Slots seed und
        # stichprobe_n gibt es nicht mehr, seit gebrauch_kwic keine eigene
        # Stichprobe mit festem Seed vorschreibt.
        recipe = RECIPES_BY_ID["gebrauch_kwic"]
        rendered = render_briefing(
            recipe, {"ausdruck": "'nachhaltig'", "achse": "model"}
        )
        self.assertIn("'nachhaltig'", rendered)
        self.assertNotIn("{ausdruck}", rendered)
        self.assertNotIn("{achse}", rendered)
        self.assertIn("Offene Slots", rendered)
        self.assertIn("{fenster}", rendered)
        self.assertIn("- fenster:", rendered)

    def test_alle_slots_gefuellt_keine_offene_sektion(self) -> None:
        recipe = RECIPES_BY_ID["profil"]
        rendered = render_briefing(recipe, {"term": "Haus"})
        self.assertNotIn("Offene Slots", rendered)
        self.assertNotIn("{term}", rendered)
        self.assertIn("word_sketch(term=Haus)", rendered)

    def test_unbekannte_slot_keys_werden_ignoriert(self) -> None:
        recipe = RECIPES_BY_ID["profil"]
        rendered = render_briefing(
            recipe, {"term": "Haus", "quatsch": "egal"}
        )
        self.assertNotIn("egal", rendered)


class TestRecipeIndex(unittest.TestCase):
    def test_index_hat_acht_zeilen_stabil_sortiert(self) -> None:
        index_text = recipe_index()
        lines = index_text.splitlines()
        self.assertEqual(len(lines), 8)
        ids = [line.split(":", 1)[0] for line in lines]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), _EXPECTED_IDS)
        for line in lines:
            self.assertIn(": ", line)

    def test_index_ist_byte_identisch_je_aufruf(self) -> None:
        self.assertEqual(recipe_index(), recipe_index())


class TestFacadeReexports(unittest.TestCase):
    """Die Fassade re-exportiert die Rezept-API funktionsgleich.

    Identitaets-Asserts sind hier bewusst vermieden: tests/conftest.py
    registriert das Copilot-Paket unter BEIDEN Importpfaden
    (``candyconc_copilot`` und ``candyconc.candyconc_copilot``), wodurch je
    Pfad eine eigene Modulinstanz existieren kann. Der Kontrakt ist die
    identische API und das identische Verhalten, nicht das Objekt.
    """

    def test_analysis_grounding_re_exportiert_rezept_api(self) -> None:
        for name in (
            "select_recipe",
            "recipe_index",
            "render_briefing",
            "Recipe",
            "RECIPES",
            "RECIPES_BY_ID",
            "get_recipe",
        ):
            self.assertTrue(hasattr(analysis_grounding, name), name)
        self.assertEqual(analysis_grounding.recipe_index(), recipe_index())
        facade_selected = analysis_grounding.select_recipe(_LIVE_P3_FRAGE)
        self.assertIsNotNone(facade_selected)
        self.assertEqual(facade_selected.id, "gebrauch_kwic")
        facade_recipe = analysis_grounding.get_recipe("profil")
        self.assertEqual(
            analysis_grounding.render_briefing(
                facade_recipe, {"term": "Haus"}
            ),
            render_briefing(get_recipe("profil"), {"term": "Haus"}),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
