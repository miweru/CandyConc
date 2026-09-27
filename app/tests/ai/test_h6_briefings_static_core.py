"""H6-Qualitätsrunde, Paket P5: Briefings + statischer Kern.

Offline, ohne LLM und ohne Index. Gepinnt werden die Daten-/Renderer-Fixes
der Gutachter-Befunde B2(1), B5(3), B6(5), B7(2)(3) und B8-S3:

* B2(1) exploration_meta: Hypothesen sind ein Deliverable-Baustein
  (Schritt 4, deliverable, Leitplanke), nicht nur permissiv erlaubt.
* B5(3) profil: der KWIC-Beleg ist ein Anschauungsbeleg, keine Gegenprobe
  einer Dependenzrelation. Fallback bei fehlendem word_sketch benennt
  collocate_stats ausdrücklich als LINEARE Fensterkollokation. Relationen
  werden im {{ev:...}}-Pfad über den rohen Relationsschlüssel referenziert.
* B6(5) assoziation: min_freq=0 (auto) statt festem 5er-Floor, der Floor
  wird deterministisch an der Knotenfrequenz kalibriert, effektive Floors
  <5 sind als explorativ zu kennzeichnen.
* B7(3) kontrast: technische Felder (split/fold/batch) sind keine
  linguistische Achse, @-Handles nur mit Streuungs-Gegenprobe berichten.
* B7(2) prompt_layout: kind='technical' wird ehrlich gerendert und zählt
  nie zu kontrastierbare_achsen.
* B8-S3: Anti-Repetitions-Regel im AUSGABEFORMAT des statischen Kerns,
  Pin STATIC_CORE_CHAR_COUNT im selben Schritt nachgezogen.

Die Trigger der vier angefassten Rezepte sind exakt gepinnt: die H6-Fixes
ändern Briefing-DATEN, nie das Routing.
"""

from __future__ import annotations

import unittest

from candyconc.candyconc_copilot import prompt_layout
from candyconc.candyconc_copilot.prompt_layout import (
    STATIC_CORE_CHAR_COUNT,
    STATIC_CORE_MAX_CHARS,
    build_static_core,
    build_turn_briefing,
)
from candyconc.candyconc_copilot.recipes import get_recipe, render_briefing


# --------------------------------------------------------------------------- #
# B2(1): exploration_meta — Hypothesen als Deliverable-Baustein               #
# --------------------------------------------------------------------------- #
class TestExplorationHypothesenBaustein(unittest.TestCase):
    _SATZ = (
        "2-3 Sprachhypothesen als eigene Punkte, je "
        "prüfbarer Satz + stützender Zahlen-/KWIC-Beleg + was "
        "sie widerlegen würde"
    )

    def test_deliverable_fordert_hypothesen_struktur(self):
        recipe = get_recipe("exploration_meta")
        self.assertIn("Fragt die Frage nach Hypothesen:", recipe.deliverable)
        self.assertIn("Sprachhypothesen als eigene Punkte", recipe.deliverable)
        self.assertIn("was sie widerlegen würde", recipe.deliverable)

    def test_leitplanke_traegt_die_hypothesen_struktur(self):
        recipe = get_recipe("exploration_meta")
        matching = [
            lp
            for lp in recipe.leitplanken
            if "Sprachhypothesen als eigene Punkte" in lp
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("widerlegen", matching[0])
        # Leitplanken-Budget (2-4) bleibt eingehalten.
        self.assertLessEqual(len(recipe.leitplanken), 4)

    def test_schritt_4_nennt_hypothesen(self):
        recipe = get_recipe("exploration_meta")
        letzter = recipe.schritte[-1]
        self.assertIn("Hypothesen", letzter.ziel)
        self.assertIn("Sprachhypothesen", letzter.tool_hinweis)

    def test_gerendertes_briefing_traegt_den_baustein(self):
        rendered = render_briefing(get_recipe("exploration_meta"))
        self.assertIn("Fragt die Frage nach Hypothesen:", rendered)
        self.assertIn(self._SATZ, rendered)


# --------------------------------------------------------------------------- #
# B5(3): profil — Anschauungsbeleg statt Gegenprobe, rel-Fallback             #
# --------------------------------------------------------------------------- #
class TestProfilAnschauungsbeleg(unittest.TestCase):
    def test_kwic_beleg_ist_anschauungsbeleg_nicht_gegenprobe(self):
        rendered = render_briefing(get_recipe("profil"), {"term": "Haus"})
        self.assertIn("Anschauungsbeleg", rendered)
        # Die alte Anweisung "KWIC-Gegenprobe ziehen" ist weg.
        self.assertNotIn("KWIC-Gegenprobe", rendered)
        # "Gegenprobe" kommt nur noch als ausdrückliche Negation vor.
        self.assertIn(
            "nie als Gegenprobe/Verifikation der Relation", rendered
        )
        for ziel in (s.ziel for s in get_recipe("profil").schritte):
            self.assertNotIn("Gegenprobe", ziel)

    def test_linearitaet_wird_explizit_benannt(self):
        rendered = render_briefing(get_recipe("profil"))
        self.assertIn(
            "run_cqlf_query matcht lineare Nachbarschaft, keine "
            "Dependenzrelation",
            rendered,
        )

    def test_fallback_bei_fehlendem_word_sketch(self):
        rendered = render_briefing(get_recipe("profil"))
        self.assertIn(
            "missing_corpus_features token_attributes.rel", rendered
        )
        self.assertIn("kein grammatisches Profil behaupten", rendered)
        self.assertIn("LINEARE Fensterkollokation", rendered)
        self.assertIn(
            "lineare Kookkurrenz ist keine Dependenzrelation", rendered
        )

    def test_leitplanke_referenziert_rohen_relationsschluessel(self):
        recipe = get_recipe("profil")
        matching = [
            lp for lp in recipe.leitplanken if "tables.nk[0].word" in lp
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("{{ev:...}}", matching[0])
        self.assertIn("Labels", matching[0])
        # Die Leitplanke ueberlebt das Rendering woertlich (kein Slot-Format
        # frisst die doppelten Klammern).
        rendered = render_briefing(recipe, {"term": "Haus"})
        self.assertIn("tables.nk[0].word", rendered)
        self.assertIn("{{ev:...}}", rendered)


# --------------------------------------------------------------------------- #
# B6(5): assoziation — adaptiver Floor im Briefing                            #
# --------------------------------------------------------------------------- #
class TestAssoziationAdaptiverFloor(unittest.TestCase):
    def test_min_freq_auto_statt_festem_floor(self):
        recipe = get_recipe("assoziation")
        rendered = render_briefing(recipe)
        self.assertIn("min_freq=0 (auto)", recipe.briefing)
        self.assertIn("min_freq=0 (auto)", rendered)
        # Kein Text des Rezepts nennt mehr den festen 5er-Parameter.
        texts = [recipe.briefing, recipe.deliverable]
        texts.extend(recipe.leitplanken)
        texts.extend(s.tool_hinweis for s in recipe.schritte)
        for text in texts:
            self.assertNotIn("min_freq=5", text)

    def test_kalibrierungstext_und_kennzeichnungspflicht(self):
        rendered = render_briefing(get_recipe("assoziation"))
        self.assertIn(
            "deterministisch an der Knotenfrequenz", rendered
        )
        self.assertIn("5 bei häufigen Knoten, bis 2 bei node_freq<50", rendered)
        self.assertIn("explorativ (n klein)", rendered)
        self.assertIn("nach f berichten", rendered)
        self.assertIn("keine Signifikanzaussagen aus ll/chi2/t", rendered)
        self.assertIn("mit KWIC-Beleg absichern", rendered)

    def test_leitplanke_gegen_manuelles_unterlaufen(self):
        recipe = get_recipe("assoziation")
        matching = [
            lp
            for lp in recipe.leitplanken
            if "automatisch kalibrierten Floor" in lp
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("f=1-Paare nie berichten", matching[0])
        self.assertLessEqual(len(recipe.leitplanken), 4)


# --------------------------------------------------------------------------- #
# B7(3): kontrast — technische Felder und Handle-Disziplin                    #
# --------------------------------------------------------------------------- #
class TestKontrastTechnischeFelderUndHandles(unittest.TestCase):
    def test_schritt_0_blockt_technische_felder(self):
        rendered = render_briefing(get_recipe("kontrast"))
        self.assertIn(
            "Technische Felder (split/fold/batch: Datenaufteilung) sind "
            "KEINE linguistische Achse",
            rendered,
        )
        self.assertIn(
            "wenn die Frage ausdrücklich die Aufteilung selbst untersucht",
            rendered,
        )
        # Hausstil-Invariante aus r4 bleibt: keine Semikola im Briefing.
        self.assertNotIn(";", rendered)

    def test_leitplanke_handle_disziplin(self):
        recipe = get_recipe("kontrast")
        matching = [lp for lp in recipe.leitplanken if "@-Handles" in lp]
        self.assertEqual(len(matching), 1)
        self.assertIn("Adressierungsartefakte", matching[0])
        self.assertIn("Streuungs-Gegenprobe", matching[0])
        self.assertIn("file-Spalte", matching[0])
        self.assertIn("nie allein als Registerbefund", matching[0])
        self.assertLessEqual(len(recipe.leitplanken), 4)


# --------------------------------------------------------------------------- #
# Routing-Regression: Trigger der vier angefassten Rezepte unverändert        #
# --------------------------------------------------------------------------- #
class TestTriggerUnveraendert(unittest.TestCase):
    _EXPECTED = {
        "exploration_meta": (
            "family:open_research",
            "family:semantic_retrieval",
            "was fällt auf",
            "was faellt auf",
            "was fällt",
            "was faellt",
            "auffällig",
            "auffaellig",
            "erkunde",
            "explorier",
            "untersuche",
            "überblick",
            "ueberblick",
            "welche themen",
            "worum geht",
            "interessant",
            "hypothese",
            # H8: Stil-Charakterisierung (hold_offen_stil).
            "charakterisier",
            "sprachstil",
            "wort:stil",
        ),
        "profil": (
            "family:word_sketch_profile",
            "word sketch",
            "word-sketch",
            "wortprofil",
            "grammatisches profil",
            "grammatische relationen",
            "grammatischen relationen",
        ),
        "assoziation": (
            "family:collocation",
            "family:term_profile",
            "kollokat",
            "kollokation",
            "kookkurrenz",
            "tritt mit",
            "zusammen mit",
            "gemeinsam mit",
            "begleitwört",
            "begleitwoert",
            "steht neben",
            "stehen neben",
            "assoziation",
        ),
        "kontrast": (
            "family:contrast_keyness",
            "typisch für",
            "typisch fuer",
            "keyness",
            "schlüsselwört",
            "schluesselwoert",
            "im vergleich zu",
            "im vergleich zum",
            "unterscheiden sich",
            "kontrastiere",
            # H8: freie Vergleichsformen (hold_kontrast_mensch_ki).
            "vergleich",
        ),
    }

    def test_trigger_exakt_gepinnt(self):
        for recipe_id, expected in self._EXPECTED.items():
            with self.subTest(recipe=recipe_id):
                self.assertEqual(get_recipe(recipe_id).trigger, expected)


# --------------------------------------------------------------------------- #
# B7(2): _render_meta_axes — technical-Zweig                                  #
# --------------------------------------------------------------------------- #
def _card(meta_axes):
    return {
        "corpus_id": "bench",
        "meta_fields": [a["field"] for a in meta_axes],
        "meta_axes": meta_axes,
        "date_fields": [],
    }


class TestRenderMetaAxesTechnical(unittest.TestCase):
    def test_technical_axis_rendered_honestly_and_not_contrastable(self):
        rendered = build_turn_briefing(
            _card(
                [
                    {"field": "split", "count": 2, "kind": "technical"},
                    {"field": "register", "count": 3, "kind": "axis"},
                    {"field": "model", "count": 1, "kind": "single"},
                ]
            )
        )
        self.assertIn(
            "split (2 Werte, technisch: Datenaufteilung, nicht "
            "kontrastierbar)",
            rendered,
        )
        self.assertIn("register (3 Werte, kontrastierbar)", rendered)
        self.assertIn("kontrastierbare_achsen: register", rendered)
        # split steht NICHT in der handlungsleitenden Liste.
        kontrast_zeile = next(
            line
            for line in rendered.splitlines()
            if line.startswith("kontrastierbare_achsen:")
        )
        self.assertNotIn("split", kontrast_zeile)

    def test_technical_only_card_has_no_contrastable_axes(self):
        rendered = build_turn_briefing(
            _card(
                [
                    {"field": "split", "count": 2, "kind": "technical"},
                    {"field": "doc_id", "count": 2000, "kind": "doc_id"},
                ]
            )
        )
        self.assertIn("kontrastierbare_achsen: keine", rendered)
        self.assertIn("technisch: Datenaufteilung", rendered)

    def test_axis_kind_rendering_unchanged(self):
        # Solange recipe_runtime kein kind='technical' liefert, rendert die
        # Karte byte-identisch wie vor dem H6-Fix.
        rendered = build_turn_briefing(
            _card([{"field": "split", "count": 2, "kind": "axis"}])
        )
        self.assertIn("split (2 Werte, kontrastierbar)", rendered)
        self.assertIn("kontrastierbare_achsen: split", rendered)
        self.assertNotIn("technisch", rendered)


# --------------------------------------------------------------------------- #
# B8-S3: statischer Kern — Anti-Repetitions-Regel + Pin                       #
# --------------------------------------------------------------------------- #
class TestStaticCoreAntiRepetition(unittest.TestCase):
    def test_ausgabeformat_traegt_die_anti_repetitions_regel(self):
        core = build_static_core()
        block = core.split("<ausgabeformat>")[1].split("</ausgabeformat>")[0]
        flat = " ".join(block.split())
        self.assertIn(
            "Jede Zahl, jedes Zitat und jeder Befund erscheint genau "
            "einmal, kein Abschnitt wiederholt einen anderen.",
            flat,
        )
        self.assertIn("Methodenvorspann maximal 2 Zeilen.", flat)

    def test_pin_und_budget_nachgezogen(self):
        core = build_static_core()
        self.assertEqual(len(core), STATIC_CORE_CHAR_COUNT)
        self.assertLessEqual(len(core), STATIC_CORE_MAX_CHARS)

    def test_byte_stabilitaet_ueber_zwei_builds(self):
        first = prompt_layout._compose_static_core()
        second = prompt_layout._compose_static_core()
        self.assertEqual(first, second)
        self.assertEqual(build_static_core(), first)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
