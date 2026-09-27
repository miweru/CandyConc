"""Context questions select collocations and use collocation evidence.

Mentions of generally frequent words can be exclusion criteria. They must
not redirect a word-context question to an overall frequency list. Check
question wording, quotation styles, allowed tools and the rendered answer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.analysis_grounding import (  # noqa: E402
    build_grounded_markdown,
)
from candyconc.candyconc_copilot.grounding_contracts import (  # noqa: E402
    _RECIPE_DEFAULT_TOOLS,
    heuristic_analysis_contract,
    select_recipe,
)
from candyconc.candyconc_copilot.grounding_facts import (  # noqa: E402
    make_evidence_item,
)

WERKZEUGE = list(_RECIPE_DEFAULT_TOOLS)

NACHTLAUF_FRAGE = (
    "Welche Wörter bilden das charakteristische unmittelbare Umfeld von "
    "‚Migration‘? Unterscheide aussagekräftige Partner von bloß allgemein "
    "häufigen Wörtern und belege die stärksten Fälle."
)


def _vertrag(frage: str):
    return heuristic_analysis_contract(
        frage, available_tools=WERKZEUGE, read_only_tools=WERKZEUGE
    )


class DieNachtlaufFrageWirdRichtigEingeordnet(unittest.TestCase):
    def test_familie_ist_kollokation_nicht_frequenz(self):
        vertrag = _vertrag(NACHTLAUF_FRAGE)
        self.assertIsNotNone(vertrag)
        self.assertEqual(vertrag.analysis_family, "collocation")

    def test_collocate_stats_ist_ueberhaupt_erst_erlaubt(self):
        # Vorher stand allowed_tools=['frequency_list'] da. Das Werkzeug,
        # das die Frage beantwortet, war nicht einmal zugelassen.
        vertrag = _vertrag(NACHTLAUF_FRAGE)
        self.assertIn("collocate_stats", vertrag.allowed_tools)

    def test_rezept_ist_assoziation(self):
        rezept = select_recipe(NACHTLAUF_FRAGE)
        self.assertIsNotNone(rezept)
        self.assertEqual(rezept.id, "assoziation")


class WeitereUmfeldformulierungen(unittest.TestCase):
    """Die Frage vermeidet das Fachwort. Andere tun das auch."""

    FRAGEN = (
        "Welche Wörter stehen im Umfeld von 'Flucht'?",
        "Zeige das Wortumfeld von 'Arbeit'.",
        "Welche Nachbarwörter hat 'Migration'?",
        "Was steht in der Umgebung von 'Asyl'?",
    )

    def test_alle_erreichen_die_kollokationsfamilie(self):
        for frage in self.FRAGEN:
            with self.subTest(frage=frage):
                vertrag = _vertrag(frage)
                self.assertIsNotNone(vertrag, "kein Vertrag")
                self.assertIn(
                    vertrag.analysis_family, ("collocation", "term_profile")
                )
                self.assertIn("collocate_stats", vertrag.allowed_tools)


class JedeAnfuehrungszeichensorte(unittest.TestCase):
    """Context questions select the same analysis family with all supported quotation styles.

Check the frequency and count branches as well as the collocation branch,
since an earlier branch can otherwise capture the question."""

    VORLAGE = (
        "Welche Wörter bilden das charakteristische unmittelbare Umfeld "
        "von {}? Unterscheide aussagekräftige Partner von bloß allgemein "
        "häufigen Wörtern."
    )

    def test_alle_vier_sorten_landen_bei_der_kollokation(self):
        for zitat in ("‚Migration‘", "'Migration'", '"Migration"', "„Migration“"):
            with self.subTest(zitat=zitat):
                frage = self.VORLAGE.format(zitat)
                self.assertEqual(_vertrag(frage).analysis_family, "collocation")
                self.assertEqual(select_recipe(frage).id, "assoziation")


class KeineFehlleitungInDieGegenrichtung(unittest.TestCase):
    """Cues werden am ZITATFREIEN Fragetext abgeglichen.

    Phrasen statt Wortstaemme genuegen NICHT. Ein Mehrwort-Zitat traegt
    die Phrase mit: „Zaehle die Treffer fuer 'im Umfeld der
    Bundesregierung'“ schlug an und wurde zur Kollokationsfrage. Eine
    Pruefung nur an Einwort-Zitaten hatte das nicht gezeigt, und der
    Kommentar im Quelltext behauptete deshalb eine Sicherheit, die nicht
    bestand.
    """

    def test_zitierte_einwort_suchbegriffe_bleiben_frequenzfragen(self):
        for frage in (
            "Wie oft kommt 'Umfeld' im Korpus vor?",
            "Wie oft kommt 'Koalitionspartner' vor?",
            "Wie häufig ist 'Partner' im Korpus?",
        ):
            with self.subTest(frage=frage):
                familie = getattr(_vertrag(frage), "analysis_family", None)
                self.assertNotEqual(familie, "collocation")

    def test_zitierte_mehrwort_suchbegriffe_ebenso(self):
        for frage in (
            "Wie oft kommt 'Umfeld von Straftätern' im Korpus vor?",
            "Zähle die Treffer für 'im Umfeld der Bundesregierung'.",
            "Wie häufig ist 'Nachbarschaft von Wohngebieten'?",
        ):
            with self.subTest(frage=frage):
                familie = getattr(_vertrag(frage), "analysis_family", None)
                self.assertNotEqual(familie, "collocation")

    def test_die_dispersionsfrage_bleibt_bei_frequenz(self):
        rezept = select_recipe(
            "Wie verteilt sich 'Regierung' im Korpus? Berechne die Dispersion."
        )
        self.assertEqual(rezept.id, "frequenz")


class DerZweigStiehltDenAnderenRoutenNichts(unittest.TestCase):
    """Der Kollokationszweig steht weit vorne und braucht Disziplin.

    Er war zuerst der einzige Cue-Zweig ganz OHNE Ausschlussliste. Eine
    Umfeldphrase irgendwo im Satz genuegte, und er nahm den Routen hinter
    ihm die Frage weg. Jeder Fall hier wurde am laufenden Code gemessen,
    bevor er hier landete.
    """

    FAELLE = (
        ("Wie entwickelt sich das Umfeld von 'Migration' über die Zeit?", "verlauf"),
        ("Erstelle ein Word Sketch für 'Zeit' und zeige das Umfeld von 'Zeit'.", "profil"),
        ("Welche Metadatenfelder beschreiben das Umfeld von 'Migration'?", "metadaten_struktur"),
        ("Wie verteilt sich das Umfeld von 'Regierung'? Berechne die Dispersion.", "frequenz"),
    )

    def test_jede_route_behaelt_ihre_frage(self):
        for frage, erwartet in self.FAELLE:
            with self.subTest(frage=frage):
                self.assertEqual(select_recipe(frage).id, erwartet)


class DieGanzeRoutingmatrix(unittest.TestCase):
    """Jede Frage, an der die Routenkorrektur gemessen wurde.

    Die erste Messlatte hatte 27 Fragen und keine einzige davon war ein
    Gruppenvergleich, eine Methodenfrage oder eine Verlaufsfrage MIT
    Umfeldphrase. Genau deshalb blieben vier Regressionen unsichtbar, bis
    adversariale Pruefer sie vorfuehrten. Diese Tabelle ist die
    nachgezogene Messlatte, und jede Zeile darin wurde einzeln am
    laufenden Code gemessen, vorher wie nachher.

    Der Kollokationszweig ist der ALLGEMEINSTE der Cue-Zweige und steht
    deshalb HINTER den spezialisierten Routen. Das allein genuegt nicht,
    denn wo eine Route ihre Frage nicht selbst erkennt und das Rezept
    bisher aus dem blossen Triggerabgleich kam, erzeugt der Zweig neu
    einen Vertrag und ueberstimmt die Triggerwahl. Dagegen steht
    ``_UMFELD_AUSSCHLUSS``.
    """

    MATRIX = (
        # (Frage, erwartetes Rezept)
        ("Registervergleich: welche Kollokationen von 'Arbeit' unterscheiden news von blog?", "kontrast"),
        ("Wie entwickelt sich das Umfeld von 'Migration' über die Wahlperioden hinweg?", "verlauf"),
        ("Wie gehe ich methodisch vor, um das Umfeld von 'Migration' zu untersuchen?", "exploration_meta"),
        ("Suche semantisch nach Stellen im Umfeld von 'Migration'.", "exploration_meta"),
        ("Wie entwickelt sich das Umfeld von 'Migration' über die Zeit?", "verlauf"),
        ("Erstelle ein Word Sketch für 'Zeit' und zeige das Umfeld von 'Zeit'.", "profil"),
        ("Welche Metadatenfelder beschreiben das Umfeld von 'Migration'?", "metadaten_struktur"),
        ("Wie verteilt sich das Umfeld von 'Regierung'? Berechne die Dispersion.", "frequenz"),
        ("Wie verteilt sich 'Regierung' im Korpus? Berechne die Dispersion.", "frequenz"),
        ("Wie oft kommt 'Umfeld von Straftätern' im Korpus vor?", "frequenz"),
        ("Wie oft kommt 'Umfeld' im Korpus vor?", "frequenz"),
        ("Wie häufig ist 'Koalitionspartner'?", "frequenz"),
        ("Welche Wörter stehen im Umfeld von 'Flucht'?", "assoziation"),
        ("Zeige das Wortumfeld von 'Arbeit'.", "assoziation"),
        ("Welche Nachbarwörter hat 'Migration'?", "assoziation"),
        ("Welche Kollokationen hat 'Arbeit' im Korpus?", "assoziation"),
        ("Was steht in der Umgebung von 'Asyl'?", "assoziation"),
    )

    def test_jede_frage_erreicht_ihr_rezept(self):
        for frage, erwartet in self.MATRIX:
            with self.subTest(frage=frage[:50]):
                rezept = select_recipe(frage)
                self.assertIsNotNone(rezept, "kein Rezept")
                self.assertEqual(rezept.id, erwartet)


class DerGruppenvergleichBleibtEinKontrast(unittest.TestCase):
    """Der schwerste Befund gegen den Kollokationszweig.

    ``same_corpus_collocation_terms`` deckt nur den Vergleich ZWEIER
    TERME im selben Korpus und liefert bei „zwischen Docset A und Docset
    B“ ausdruecklich eine leere Liste. Der Zweig riss die
    Docset-Kontrastroute deshalb an sich: aus acht Werkzeugen wurden
    vier, ohne keyness, contrast_collocates, create_docset und
    metadata_values, und der Vorplan plante EINEN globalen
    Kollokationsaufruf ueber das Gesamtkorpus.

    Damit haette die Routenkorrektur ihren eigenen Ausloeser eine
    Familie weiter wiederholt: gefragt ist A gegen B, geantwortet wuerde
    mit dem globalen Umfeld des Knotens. Betroffen war auch die Achse
    Mensch gegen KI, die zentrale Vergleichsachse dieses Repos.

    Die erste Messlatte enthielt keine einzige Gruppenvergleichsfrage.
    Genau deshalb blieb der Defekt unsichtbar, bis ein adversarialer
    Pruefer ihn vorfuehrte.
    """

    WERKZEUGE = sorted(
        set(list(_RECIPE_DEFAULT_TOOLS) + ["contrast_collocates", "compare_collocates"])
    )

    FRAGEN = (
        "Vergleiche die Kollokationen von 'Mensch' zwischen den Registern news und blog.",
        "Vergleiche die Kollokate von 'Arbeit' zwischen Docset A und Docset B.",
        "Vergleiche die Kollokationen von 'Arbeit' zwischen menschlichen und KI-generierten Texten.",
        "Kontrastiere das unmittelbare Umfeld von 'Klima' in den Reden vor 2000 gegenüber denen nach 2010.",
        "Vergleiche die Kollokate von 'Arbeit' zwischen Teilkorpus A und Teilkorpus B.",
        "Vergleiche die Kollokate von 'Migration' zwischen den Reden der AfD und denen der Grünen.",
    )

    def _kontrakt(self, frage: str):
        return heuristic_analysis_contract(
            frage,
            available_tools=self.WERKZEUGE,
            read_only_tools=self.WERKZEUGE,
        )

    def test_die_familie_bleibt_der_kontrast(self):
        for frage in self.FRAGEN:
            with self.subTest(frage=frage):
                self.assertEqual(
                    self._kontrakt(frage).analysis_family, "contrast_keyness"
                )

    def test_die_werkzeuge_des_kontrasts_bleiben_erhalten(self):
        # Ohne diese vier ist ein Kontrast nicht rechenbar. Der
        # Orchestrator exponiert ausschliesslich allowed_tools, ein
        # trotzdem gerufener Name wird als nicht exponiert geblockt.
        for frage in self.FRAGEN:
            with self.subTest(frage=frage):
                erlaubt = set(self._kontrakt(frage).allowed_tools)
                for werkzeug in (
                    "keyness",
                    "contrast_collocates",
                    "create_docset",
                    "metadata_values",
                ):
                    self.assertIn(werkzeug, erlaubt)

    def test_das_rezept_bleibt_kontrast(self):
        for frage in self.FRAGEN:
            with self.subTest(frage=frage):
                self.assertEqual(select_recipe(frage).id, "kontrast")


class DieAntwortNenntKollokateStattKorpusfrequenzen(unittest.TestCase):
    """Der Beweis ueber die ganze Kette, mit BEIDEN Evidenzarten im Topf."""

    KOLLOKATION = {
        "status": "success",
        "requested_term": "Migration",
        "effective_term": "Migration",
        "term_mode": "surface_or_cql",
        "window": 5,
        "within_sentence": True,
        "min_freq": 5,
        "node_frequency": 3075,
        "sort_by": "logdice",
        "result_count": 542,
        "method": {"attribute": "word", "floor_mode": "adaptive"},
        "scope": {"corpus_id": "sample_corpus", "level": "corpus"},
        "rows": [
            {"word": "irreguläre", "f": 412, "logdice": 9.81, "ll": 1840.2},
            {"word": "Fluchtursachen", "f": 388, "logdice": 9.44, "ll": 1702.0},
            {"word": "Steuerung", "f": 301, "logdice": 8.97, "ll": 1355.7},
        ],
    }
    # Corpus-wide frequencies must not replace collocation evidence.
    FREQUENZLISTE = {
        "status": "success",
        "group_by": "word",
        "total": 49996,
        "truncated": True,
        "denominator_tokens": 273550093,
        "denominator_scope": "corpus",
        "scope": {"corpus_id": "sample_corpus", "level": "corpus"},
        "rows": [
            {"word": "Beifall", "f": 946766, "per_million": 3461.0},
            {"word": "Herr", "f": 857969, "per_million": 3136.4},
        ],
    }

    def _antwort(self) -> str:
        vertrag = _vertrag(NACHTLAUF_FRAGE)
        posten = [
            make_evidence_item(
                item_id="ev1", tool="collocate_stats", tool_call_id="c1",
                query={"term": "Migration"}, output=self.KOLLOKATION,
                analysis_family="collocation",
            ),
            make_evidence_item(
                item_id="ev2", tool="frequency_list", tool_call_id="c2",
                query={}, output=self.FREQUENZLISTE,
                analysis_family="collocation",
            ),
        ]
        return build_grounded_markdown(vertrag, [], posten, evidence_gaps=[])

    def test_die_echten_kollokate_stehen_in_der_antwort(self):
        antwort = self._antwort()
        for wort in ("irreguläre", "Fluchtursachen", "Steuerung"):
            self.assertIn(wort, antwort)

    def test_die_korpusweiten_haeufigsten_woerter_stehen_nicht_darin(self):
        # Der Kern des Befunds. Die Frage wollte diese Menge ausschlieszen.
        antwort = self._antwort()
        self.assertNotIn("Beifall", antwort)
        self.assertNotIn("946766", antwort)

    def test_die_antwort_nennt_knoten_fenster_und_schwelle(self):
        antwort = self._antwort()
        self.assertIn("Migration", antwort)
        self.assertIn("Fenster ±5", antwort)
        self.assertIn("Mindestfrequenz 5", antwort)


if __name__ == "__main__":
    unittest.main()
