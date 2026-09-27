# -*- coding: utf-8 -*-
"""Gate 13: was die Kollokationszahlen zaehlen, und was ueber sie gilt.

Erste Runde, drei Befunde am eigenen Werkzeug:

1. ``f``/``observed`` sind PAAR-Kookkurrenzen. Ein Token im Fenster mehrerer
   Anker zaehlt je Anker (``collocation_engine``, ``pair_semantics=True``).
   Am Testindex traegt Knoten "die" die Zeilen ``ganze`` f=14 bei
   Korpusfrequenz 13, ``Idee`` f=6 bei 5, ``Bahnhofsklatscher`` f=3 bei 1.
2. ``metric_units`` war deklariert, von ``word_sketch`` kopiert und wurde nie
   geliefert.
3. Die logDice-Erklaerung im Prompt behauptete Korpusgroessen-Unabhaengigkeit,
   die ``analysis_defaults`` fuer den Paar-Ereignisraum zurueckgenommen hatte.

Zweite Runde, der adversariale Prueflauf gegen genau diesen Commit, und er
hat zwei eigene Fehler gefunden:

4. Die Ruecknahme war eine UEBERKORREKTUR. "Das Maximum 14 der Standardform
   gilt hier nicht" ist FALSCH: ``logdice = 14 + log2(dice)`` und ``dice <= 1``
   gilt konstruktiv, weil O11 <= R1 und O11 <= C1. Unabhaengig nachgemessen
   ueber 1891 Zeilen an neun Knoten: null Zeilen ueber 14, und
   ``14 + log2(dice)`` reproduziert jeden Wert exakt. Der begruendende
   Kommentar in ``analysis_defaults`` sagt selbst "waehrend Rychlys Skala bei
   14 deckelt", bestreitet die Schranke also gar nicht. Zurueckzunehmen war
   die VERGLEICHBARKEIT.
5. Die Vorfassung dieser Tests pinnte den WORTLAUT (``assert "Maximum 14" in
   doc``) und hielt die falsche Aussage damit fest, statt sie zu fangen. Sie
   pruefen jetzt Eigenschaften und, wo moeglich, Zahlen.
"""

from __future__ import annotations

import math
import os

import pytest
from jsonschema import validate as _json_validate

from candyconc.analysis_defaults import method_statistics
from candyconc.candyconc_copilot import prompt_layout as pl
from candyconc.candyconc_copilot import prompts as P

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


def _flach(text: str) -> str:
    """Zeilenumbrueche wegnormalisieren, damit ein Umbruch keinen Test faellt."""
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# Doku- und Schema-Anker: brauchen keinen Index, koennen also nicht skippen.   #
# --------------------------------------------------------------------------- #
class TestVertragOhneIndex:
    def test_prompt_sagt_die_wahrheit_ueber_f(self):
        """Der Prompt beschrieb f nach der Evert-Umstellung falsch.

        Bis dahin zaehlte f paargewichtet, ein Token im Fenster mehrerer
        Anker also je Anker, und der Satz "f kann die Korpusfrequenz des
        Kollokats uebersteigen" stimmte. Die Umstellung auf Everts
        Distanztafel hat auf VEREINIGUNG gedreht (pair_semantics=False),
        das Glossar mitgezogen und den Prompt stehen lassen. Damit sagten
        zwei Flaechen DERSELBEN Antwort das Gegenteil voneinander ueber
        die zentrale Zahl.

        An Daten geprueft: 2060 Zeilen ueber fuenf Knoten am Testindex,
        NULL Faelle von f > f2. Groesstes f war "und" bei Knoten "die" mit
        f=167 gegen f2=797.

        Die Absicht des urspruenglichen Tests bleibt: f ist keine
        Vorkommenszahl im Korpus und darf nicht als "kommt N-mal vor"
        berichtet werden. Nur die Begruendung ist jetzt die richtige.
        """
        doc = _flach(P.TOOLS_DOC)
        assert "Fenster-VEREINIGUNG" in doc
        assert "EINMAL" in doc
        assert "f <= f2" in doc
        assert "kommt N-mal vor" in doc
        # Und die widerlegte Behauptung steht nirgends mehr.
        assert "kann die Korpusfrequenz des Kollokats" not in doc
        assert "zählt je Anker" not in doc

    def test_prompt_traegt_die_widerlegte_behauptung_nicht_mehr(self):
        """Der eigentliche Defekt war der WIDERSPRUCH, nicht die Wortwahl.

        Dieselbe Antwort trug beide Saetze: der Prompt "zaehlt je Anker,
        kann uebersteigen", das gelieferte Glossar "zaehlt einmal,
        uebersteigt nicht". Ein Modell, das beides liest, kann die zentrale
        Zahl nicht deuten. Der Vergleich der beiden gelieferten Flaechen
        steht in TestVerhaltenAmIndex, hier nur der Prompt.
        """
        doc = _flach(P.TOOLS_DOC)
        assert "je Anker" not in doc
        assert "kann die Korpusfrequenz" not in doc

    def test_logdice_nimmt_die_vergleichbarkeit_zurueck_nicht_die_schranke(self):
        doc = _flach(P.TOOLS_DOC)
        assert "korpusgrößenunabhängig" not in doc
        assert "zwischen ähnlich gebauten Korpora besser" not in doc
        assert "über Knoten und Korpora nicht vergleichbar" in doc
        # Befund B1: die falsche Aussage darf an KEINER Oberflaeche stehen.
        for flaeche in (doc, _flach(P.GLOSSAR)):
            assert "Maximum 14 der Standardform gilt hier nicht" not in flaeche
            assert "Maximum 14 gilt dort nicht" not in flaeche

    def test_prompt_und_rest_metadaten_sagen_dasselbe_ueber_logdice(self):
        """Der eigentliche Defekt war der WIDERSPRUCH zwischen zwei Flaechen."""
        eintrag = next(
            e for e in method_statistics("collocates") if e["key"] == "logdice"
        )
        erklaerung = _flach(eintrag["explanation"])
        # Seit dem 2026-08-29 traegt die Spalte logdice Rychlys Definition
        # auf den WORTFREQUENZEN, und damit gilt seine Aussage wieder. Was
        # nicht ueber Knoten vergleichbar ist, heisst logdice_window.
        assert "Rychlý 2008" in erklaerung
        # Wortlaut seit 1456cd15d: "Der Wert hängt nicht von der Korpusgröße
        # ab", dazu die Abhaengigkeit von der Fensterbreite.
        assert "nicht von der Korpusgröße ab" in erklaerung
        assert "nur bei gleicher Fensterbreite vergleichbar" in erklaerung
        fenster = _flach(next(
            e for e in method_statistics("collocates")
            if e["key"] == "logdice_window")["explanation"])
        assert "NICHT über Knoten oder Korpora" in fenster
        assert "NICHT logDice nach Rychlý" in fenster
        doc = _flach(P.TOOLS_DOC)
        assert "nicht vergleichbar" in doc
        # Beide Flaechen sagen dasselbe ueber die 14: die Methodenerklaerung
        # "kann ... der Wert über 14 liegen", der Prompt nennt die Bedingung.
        # "stets <=14" war falsch, die Engine liefert 14,585 fuer "alpha beta
        # beta beta gamma" (tests/core/test_logdice_explanation.py).
        assert "über 14" in erklaerung
        assert "logdice: über 14 nur bei f > node_frequency" in doc
        assert "stets <=14" not in doc

    def test_word_sketch_behaelt_die_standardform(self):
        """Gegenprobe zur Ueberkorrektur in die andere Richtung.

        Die Ruecknahme der VERGLEICHBARKEIT gilt nur fuer den
        Paar-Ereignisraum. Word Sketches rechnen auf Tokenzahlen, dort bleibt
        Rychlys Aussage richtig.
        """
        eintrag = next(
            e for e in method_statistics("wordsketch") if e["key"] == "logdice"
        )
        # Die Erwartung folgt seit 1456cd15d der belegten Aussage (Rychlý
        # 2008, RASLAN S. 9): 14 erreicht ein Paar, dessen Woerter immer
        # gemeinsam vorkommen. Im Word Sketch gilt dieses Maximum, weil Paare
        # gezaehlt werden. Eine Schwelle "ab 7 bemerkenswert" nennt Rychlý
        # nicht, deshalb steht sie auch im Glossar nicht mehr.
        erklaerung = _flach(eintrag["explanation"])
        assert "nicht von der Korpusgröße ab" in erklaerung
        assert "14 erreicht ein Paar, dessen Wörter immer gemeinsam vorkommen" in erklaerung
        assert eintrag["reference"] == "Rychlý 2008"
        glossar = _flach(P.GLOSSAR)
        assert "ab 7" not in glossar and "Faustregel" not in glossar
        assert "14, wenn beide Wörter immer gemeinsam vorkommen" in glossar
        assert "Schwelle für bemerkenswerte Kollokationen gibt er nicht an" in glossar

    def test_delta_p_ist_an_die_rechnung_gebunden(self):
        """Befund B2: die alte Definition beschrieb Gries' Tokentabelle."""
        doc = _flach(P.TOOLS_DOC)
        # Befund B2 war, dass die Definition Gries' Tokentabelle beschrieb,
        # waehrend die Engine im Paar-Ereignisraum rechnete. Seit dem
        # 2026-08-29 steht delta-P auf Everts Distanztafel, und die Doku
        # muss deren Randsummen benennen statt eine Tabelle zu dementieren.
        assert "Distanztafel" in doc
        assert "|W(u)|" in doc
        assert "P(collocate|node) - P(collocate|nicht node)" not in doc
        assert "beide in [-1,1]" not in doc

    def test_lexical_diversity_nennt_die_zaehlweise(self):
        doc = _flach(P.TOOLS_DOC)
        assert "n_types zählt case-SENSITIV" in doc
        assert "frequency_list faltet Case" in doc

    def test_schema_deklariert_nur_die_eigenen_spalten(self):
        units = tw.COLLOCATE_RESPONSE["properties"]["metric_units"]
        props = set(units["properties"])
        assert props == {
            "f",
            # f2 stand hier frueher als PHANTOM aus der word_sketch-Kopie und
            # wurde deshalb gestrichen: die Spalte gab es in dieser Zeile
            # nicht. Sie gibt es jetzt. Die Engine rechnete f(v) fuer Rychlys
            # Nenner und warf es weg, zwei keep-Listen liessen es nicht
            # durch, und ohne f(v) war logdice = 14 + log2(2*O11/(f(u)+f(v)))
            # nicht nachrechenbar, weil f(u) als node_frequency im Kopf steht
            # und f(v) nirgends stand. Der Eintrag beschreibt also wieder
            # eine echte Spalte, nicht mehr eine erfundene.
            "f2",
            "observed",
            "expected",
            "node_frequency",
            "min_freq",
            "rank",
        }
        # Die uebrigen word_sketch-Spalten bleiben draussen: die gibt es hier
        # weiterhin nicht.
        for fremd in ("f2_basis", "score", "frequency"):
            assert fremd not in props
        assert "metric_units" in tw.COLLOCATE_RESPONSE["required"]

    def test_netzwerk_bekommt_dieselbe_beschriftung(self):
        """Befund B3/B8: das Nachbarwerkzeug liefert dieselben Paarzahlen."""
        schema = tw.COLLOCATION_NETWORK_RESPONSE
        assert "metric_units" in schema["properties"]
        assert "metric_units" in schema["required"]
        doc = _flach(P.TOOLS_DOC)
        assert "freq = dasselbe PAAR-gezaehlte f wie bei collocate_stats" in doc

    def test_zusammengesetzter_turn_prompt_widerspricht_sich_nicht(self):
        """Befund B5 (Blocker), an der Naht gemessen, an der er auftrat.

        Der Systemprompt eines Turns ist nicht TOOLS_DOC allein: das
        Rezept-Briefing wird dazukomponiert. Das Briefing des Rezepts
        "assoziation", also genau des Rezepts, das Kollokationsfragen routet,
        behauptete weiter Korpusgroessen-Unabhaengigkeit und labelte f als
        "gemeinsame Frequenz". Beides stand im SELBEN Prompt, der es zwei
        Absaetze weiter oben widerrief. Zwei Bloecke einzeln zu pruefen haette
        das nie gefunden.
        """
        from candyconc.candyconc_copilot import recipe_runtime as rr

        prompt = rr.build_turn_system_prompt(
            {"corpus_tokens": 56191}, "assoziation", None
        )
        assert len(prompt) > 20000, "Prompt unerwartet klein, Probe wertlos"
        for zurueckgenommen in (
            "von der Korpusgroesse unabhaengig",
            "f (gemeinsame Frequenz)",
            "korpusgrößenunabhängig",
            "Maximum 14 der Standardform gilt hier nicht",
            "Maximum 14 gilt dort nicht",
        ):
            assert zurueckgenommen not in prompt, zurueckgenommen
        # Und die korrigierten Aussagen sind wirklich drin.
        # Beide Flaechen muessen dieselbe Zaehlweise nennen: das Briefing
        # ueber das Rezept, die Werkzeugdoku ueber die Einheiten.
        assert "Vereinigung der Fenster" in prompt
        assert "logdice: über 14 nur bei f > node_frequency" in prompt
        assert "stets <=14" not in prompt
        assert "ab 7 bemerkenswert" not in prompt

    def test_statischer_kern_haelt_das_budget(self):
        kern = len(pl.build_static_core())
        assert kern == pl.STATIC_CORE_CHAR_COUNT, (
            f"Kern {kern}, Pin {pl.STATIC_CORE_CHAR_COUNT}"
        )
        assert kern <= pl.STATIC_CORE_MAX_CHARS


# --------------------------------------------------------------------------- #
# Verhalten am echten Index.                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestVerhaltenAmIndex:
    def test_metric_units_kommt_wirklich_an(self, active_index):  # noqa: F811
        ergebnis = tw.collocate_stats_tool(term="die", window=5, min_freq=2)
        assert "metric_units" in ergebnis, "deklariert, aber nicht geliefert"
        einheiten = ergebnis["metric_units"]
        assert set(einheiten) == {
            "f",
            "f2",
            "observed",
            "expected",
            "node_frequency",
            "min_freq",
            "rank",
        }
        assert "VEREINIGUNG der Fenster" in einheiten["f"]
        assert "Korpusfrequenz" in einheiten["f"]
        # Und der Eintrag nennt die Formel, die er ermoeglicht.
        assert "logdice" in einheiten["f2"]
        zeile = ergebnis["rows"][0]
        import math as _math
        von_hand = 14.0 + _math.log2(
            2.0 * zeile["f"] / (ergebnis["node_frequency"] + zeile["f2"])
        )
        assert abs(von_hand - zeile["logdice"]) < 5e-4, (von_hand, zeile)
        # Die Asymmetrie: der Knoten wird ungewichtet gezaehlt, die Kollokate
        # nicht. Wer beide fuer dasselbe Schema haelt, rechnet falsche Anteile.
        assert "kein Anteil" in einheiten["node_frequency"]
        _json_validate(ergebnis, tw.COLLOCATE_RESPONSE)

    def test_glossar_und_prompt_sagen_dasselbe_ueber_f(self, active_index):  # noqa: F811
        """Beide gelieferten Flaechen, nebeneinander gelegt.

        Nicht die Wortgleichheit wird geprueft, sondern dass keine der
        beiden die Aussage der anderen widerlegt: Vereinigung gegen
        Paargewichtung, einmal gegen je Anker, uebersteigt nicht gegen
        kann uebersteigen.
        """
        glossar = _flach(
            tw.collocate_stats_tool(term="die", window=5, min_freq=2)["metric_units"]["f"]
        )
        doc = _flach(P.TOOLS_DOC)
        assert "VEREINIGUNG" in glossar and "VEREINIGUNG" in doc
        for widerlegt in ("je Anker", "kann die Korpusfrequenz"):
            assert widerlegt not in glossar
            assert widerlegt not in doc
        # Die positive Klasse: beide sagen, dass f die Korpusfrequenz NICHT
        # uebersteigt. Ohne sie bestuende der Test auch auf zwei leeren Texten.
        assert "übersteigt" in glossar
        assert "f <= f2" in doc

    def test_netzwerk_liefert_metric_units(self, active_index):  # noqa: F811
        ergebnis = tw.collocation_network_tool(term="die", min_count=2, max_nodes=30)
        assert "metric_units" in ergebnis, "deklariert, aber nicht geliefert"
        assert "VEREINIGUNG der Fenster" in ergebnis["metric_units"]["freq"]
        _json_validate(ergebnis, tw.COLLOCATION_NETWORK_RESPONSE)

    def test_f_bleibt_unter_der_korpusfrequenz(self, active_index):  # noqa: F811
        """Die UMKEHRUNG des Vorgaengertests, und sie ist der Fortschritt.

        Bis zum 2026-08-29 zaehlte die Engine im Paar-Ereignisraum, und
        dieser Test verlangte den Nachweis, dass f die Korpusfrequenz
        WIRKLICH uebersteigt: am Testindex taten das 144 Zeilen, Zeuge
        war ``ganze`` mit f=14 bei Korpusfrequenz 13.

        Seit der Umstellung auf Everts Kontingenztafel zaehlt die Engine
        die Vereinigung der Fenster. Ein Token zaehlt einmal, egal in wie
        vielen Fenstern es liegt, und damit ist f wieder eine Tokenzahl.
        Die Eigenschaft, die der Vorgaenger BEWIES, ist keine mehr, und der
        Test prueft jetzt die staerkere: KEINE Zeile darf darueber liegen.

        Das ist zugleich die Reparatur eines Befundes, den eine
        Professorin-Subagentin am 2026-08-29 als toedlich eingestuft hat:
        "f wird als blanke Frequenz gedruckt" war unter Paarsemantik
        falsch. Jetzt ist f eine blanke Frequenz.
        """
        zeilen = tw.collocate_stats_tool(term="die", window=5, min_freq=2)["rows"]
        assert zeilen, "leere Kollokatliste, der Befund waere unpruefbar"
        ueber, verglichen = [], 0
        for zeile in zeilen:
            try:
                korpus = tw.query_count_tool(query=zeile["word"]).get("total")
            except tw.ToolInputError:
                # Einzelne Kollokate sind CQL-Schluesselwoerter ("and") und
                # laufen als Klartext in den Parser. Ehrlich uebergehen.
                continue
            if not isinstance(korpus, int):
                continue
            verglichen += 1
            if zeile["f"] > korpus:
                ueber.append((zeile["word"], zeile["f"], korpus))
        # Ohne positive Klasse prueft der Test nichts: waeren alle
        # Vergleiche uebersprungen, waere die leere Liste kein Befund.
        assert verglichen > 200, f"nur {verglichen} Zeilen verglichen"
        assert not ueber, (
            "f uebersteigt die Korpusfrequenz. Das war unter Paarsemantik "
            "erwartbar, unter Everts Union-Zaehlung ist es ein Defekt: "
            + repr(ueber[:5])
        )

    def test_beide_logdice_spalten_rechnen_ihre_eigene_formel(self, active_index):  # noqa: F811
        """Zwei Spalten, zwei Nenner, und keine darf die andere sein.

        Die Vorfassung prueste ``logdice == 14 + log2(dice)`` auf jeder
        Zeile. Das gilt seit dem 2026-08-29 nur noch fuer
        ``logdice_window``: ``dice`` steht auf Everts Distanztafel und hat
        den Nenner |W(u)| + f(v), waehrend ``logdice`` Rychlys Definition
        von 2008 mit dem Nenner f(u) + f(v) traegt. Beide zusammen zu
        pruefen war der Punkt, an dem die Vorfassung eine kaputte Spalte
        fuer die kanonische gehalten haette.

        f(v) kommt aus dem LEXIKON, nicht aus ``query_count``: die
        Klartextabfrage faltet Gross- und Kleinschreibung und trifft
        mehrere Wort-IDs. Eine erste Fassung dieser Pruefung verglich gegen
        ``query_count`` und meldete 791 von 1551 Zeilen als abweichend,
        obwohl die Engine exakt rechnete.
        """
        from candyconc.core.collocation_engine import CollocationEngine

        eng = CollocationEngine(_INDEX_PATH)
        eng.load()
        lex = eng._get_lexicon("word")
        geprueft = 0
        for term in ("die", "Menschen", "Idee", "Kinder", "und"):
            term_id = eng._resolve_term_id(term, lex)
            m = int(eng._get_term_positions(
                term, attr="word", term_id=term_id, lexicon=lex).size)
            rahmen = eng.collocate_stats(term, min_count=1, cache_mode="off")
            for _, zeile in rahmen.iterrows():
                # f(v) kommt aus der ZEILE. Seit die Kollokatseite mit dem
                # Knoten faltet, ist eine Zeile eine Schreibungsklasse, und
                # f2 traegt deren Summe: fuer und/Und/UND 919, waehrend das
                # Lexikon fuer "und" 797 fuehrt. Die Vorfassung schlug im
                # Lexikon nach und meldete deshalb eine Abweichung von 0,084,
                # obwohl beide Spalten aus den EIGENEN Werten der Zeile exakt
                # reproduzieren. Diese Fassung prueft genau das: dass sich die
                # Zeile aus sich selbst herleiten laesst.
                f_v = zeile["f2"]
                dice = zeile["dice"]
                if not f_v or not dice:
                    continue
                geprueft += 1
                # Rychly 2008, kanonisch und namenlos gefuehrt.
                assert zeile["logdice"] <= 14.0 + 1e-9, (term, zeile["word"])
                rychly = 14.0 + math.log2(2.0 * zeile["observed"] / (m + f_v))
                assert abs(zeile["logdice"] - rychly) < 5e-4, (
                    term, zeile["word"], zeile["logdice"], rychly)
                # Log-Transformation von Everts Dice, anderer Nenner.
                fenster = 14.0 + math.log2(dice)
                assert abs(zeile["logdice_window"] - fenster) < 5e-4, (
                    term, zeile["word"], zeile["logdice_window"], fenster)
        assert geprueft > 500, f"nur {geprueft} Zeilen geprueft"

    def test_observed_ist_dieselbe_zahl_wie_f(self, active_index):  # noqa: F811
        ergebnis = tw.collocate_stats_tool(term="die", window=5, min_freq=2)
        for zeile in ergebnis["rows"][:40]:
            assert zeile["observed"] == zeile["f"], zeile["word"]

    def test_typenzahlen_divergieren_und_werden_benannt(self, active_index):  # noqa: F811
        """n_types (case-sensitiv) gegen frequency_list total (case-gefaltet)."""
        vielfalt = tw.lexical_diversity_tool()
        liste = tw.frequency_list_tool(limit=1)
        typen = vielfalt["n_types"]
        klassen = liste["total"]
        assert typen > klassen, (
            f"n_types={typen} <= frequency_list total={klassen}: die "
            "Zaehlweisen fielen zusammen, dann waere der Hinweis falsch"
        )
        # Lowercasing separates the 25 classes that casefold joins through
        # sharp s and ss, giving 11,209 + 25 = 11,234 classes.
        assert (typen, klassen) == (12203, 11234)
