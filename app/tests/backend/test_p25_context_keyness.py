# -*- coding: utf-8 -*-
"""P2.5: Knotenkontext gegen den REST des Korpus.

Die Vorfassung dieser Datei hat den Defekt ihres Pruefobjekts MITKODIERT.
Sie rechnete die Segmentmasse selbst als ``sum(e - s + 1)`` und teilte
damit genau die Fehlannahme, die zu pruefen gewesen waere:
``coverage_sweep_arrays`` liefert HALBOFFENE Segmente ``[start, end)``
(``CoverageSegment``: "end: one past last position (half-open)", und die
Segmente sind dort schon als "disjoint" beschrieben). Der Test
"test_union_ist_kleiner_als_die_segmentmasse" bestand nur deshalb: auf
korrekter Lesart ist die Positionsmenge GLEICH der Segmentmasse.

Was der Fehler kostete, am Testindex gemessen: 8289 wahre Positionen
gegen 10005 gemeldete (+20,7 Prozent), davon 857 Knotenpositionen, weil
das Verschmelzen mit ``+1`` ueber die Luecke hinweglief, die der Sweep an
der Knotenposition laesst. In der Ergebnistabelle stand ``die`` dadurch
auf Rang 1 mit log_ratio 8,81 statt auf Rang 293 mit 0,11.

Die Tests pruefen jetzt gegen ein UNABHAENGIGES Orakel: die Engine
rechnet die Fenstermasse selbst, in
``coverage_sweep.total_context_mass_arrays``.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from candyconc.services.tools.context_keyness import context_token_counts

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


def _sweep(backend, query, fenster=5):
    """Dieselben Segmente wie das Pruefobjekt, aber unabhaengig geholt."""
    from candyconc.core.coverage_sweep import coverage_sweep_arrays
    from candyconc.core.cql_engine import search_cql_match_arrays_backend

    gesamt = int(backend.token_store.token_count)
    # Dasselbe Limit wie der Produktivpfad (context_keyness.py:63). Mit
    # 5.000.000 kappte die Gegenrechnung am 273M-Korpus, waehrend das
    # Pruefobjekt vollstaendig zaehlte: "der" hat dort 8.402.304 Treffer,
    # "die" 6.836.440. Die Probe verglich dann eine vollstaendige mit einer
    # unvollstaendigen Zahl und meldete einen Bruch, den es nicht gab.
    starts, _e = search_cql_match_arrays_backend(
        backend, query, limit=2_000_000_000
    )
    anker = np.asarray(starts, dtype=np.int64)
    s, e, w = coverage_sweep_arrays(
        anchors=anker, spans=np.ones_like(anker),
        window_left=fenster, window_right=fenster,
        boundaries=backend.boundaries, within_sentence=True,
        total_tokens=gesamt, pair_semantics=False,
    )
    return (
        anker,
        np.asarray(s, dtype=np.int64),
        np.asarray(e, dtype=np.int64),
        np.asarray(w, dtype=np.int64),
        gesamt,
    )


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestGegenDasOrakelDerEngine:
    def test_positionen_gleich_der_engine_masse(self, active_index):  # noqa: F811
        """Das entscheidende Mass, gegen die Rechnung der Engine selbst."""
        from candyconc.core.coverage_sweep import total_context_mass_arrays

        b = active_index.fast_index
        _a, s, e, w, _g = _sweep(b, 'cql:[word="die"]')
        orakel = total_context_mass_arrays(s, e, w)
        _freq, positionen, _tr, _ohne = context_token_counts(
            b, 'cql:[word="die"]', window_left=5, window_right=5
        )
        assert positionen == orakel, (positionen, orakel)
        # Und das Orakel ist wirklich die HALBOFFENE Masse, nicht +1 je Segment.
        assert orakel == int((e - s).sum())
        assert orakel != int((e - s + 1).sum()), (
            "halboffen und inklusiv fallen hier zusammen, der Test waere blind"
        )

    def test_der_knoten_steht_nicht_in_seinem_eigenen_fenster(self, active_index):  # noqa: F811
        """Der Sweep laesst die Knotenposition aus, der Code darf sie nicht
        wieder hineinverschmelzen.

        Positive Klasse: es MUSS Anker geben, die im Fenster eines ANDEREN
        Ankers liegen, sonst waere die Zahl trivial 0 und der Test leer.
        """
        b = active_index.fast_index
        anker, s, e, _w, gesamt = _sweep(b, 'cql:[word="die"]')
        maske = np.zeros(gesamt, dtype=bool)
        for x, y in zip(s.tolist(), e.tolist()):
            maske[x:y] = True
        anker_im_fenster = int(maske[anker].sum())
        assert 0 < anker_im_fenster < anker.size, anker_im_fenster

        freq, _pos, _tr, _ohne = context_token_counts(
            b, 'cql:[word="die"]', window_left=5, window_right=5
        )
        # Das Knotenwort darf nur so oft vorkommen, wie Anker echt in
        # fremden Fenstern liegen.
        assert freq.get("die", 0) == anker_im_fenster, (
            freq.get("die"), anker_im_fenster
        )

    def test_satzgrenze_wird_nicht_ueberlesen(self, active_index):  # noqa: F811
        """Das ueberzaehlige Token der Vorfassung las an jeder rechten
        Segmentkante das erste Token des NAECHSTEN Satzes."""
        b = active_index.fast_index
        _a, s, e, _w, gesamt = _sweep(b, 'cql:[word="die"]')
        satz = b.boundaries.clip_bounds_array(True)
        assert satz is not None and satz.size > 0
        # Kein Segmentende darf ueber die naechste Satzgrenze hinausragen:
        # e ist exklusiv, also muss e <= naechste Grenze gelten.
        naechste = np.searchsorted(satz, s, side="right")
        gueltig = naechste < satz.size
        assert bool(gueltig.any())
        assert bool(np.all(e[gueltig] <= satz[naechste[gueltig]])), (
            "Segment ragt ueber die Satzgrenze"
        )

    def test_positionen_zerfallen_lueckenlos(self, active_index):  # noqa: F811
        """Unlabelled positions do not enter labelled frequency denominators.

Check that labelled frequencies plus unlabelled positions account for
all positions while rates use the labelled population."""
        b = active_index.fast_index
        freq, positionen, _tr, ohne = context_token_counts(
            b, 'cql:[word="die"]', window_left=5, window_right=5
        )
        assert sum(freq.values()) + ohne == positionen

    def test_kontextzahl_uebersteigt_nie_die_korpusfrequenz(self, active_index):  # noqa: F811
        b = active_index.fast_index
        lex = b.lexicons.word
        freq, _p, _t, _o = context_token_counts(
            b, 'cql:[word="die"]', window_left=5, window_right=5
        )
        assert len(freq) > 500
        verletzt = [
            (w, c) for w, c in freq.items()
            if int(lex.get_id(w)) > 0
            and c > int(lex.get_freqs_for_ids(np.array([lex.get_id(w)], dtype=np.int64))[0])
        ]
        assert not verletzt, verletzt[:5]

    def test_die_paarzaehlung_verletzt_sie_sehr_wohl(self, active_index):  # noqa: F811
        """Gegenprobe: ohne sie waere der vorige Test moeglicherweise leer.

        BENCH-ANKER: "ganze" mit f=14 ist eine Zahl des Testindex, auf
        den die Suite festgelegt ist. Auf einem anderen Korpus schlaegt
        die Probe fehl, ohne dass etwas kaputt waere. Der Anker wird
        NICHT verallgemeinert: er ist der Beleg, dass der Kontrast zur
        Paarzaehlung ueberhaupt eine positive Klasse hat.
        """
        ergebnis = tw.collocate_stats_tool(term="die", window=5, min_freq=2)
        # VOLLE Liste: die Default-Sortierung ist logdice und hat sich am
        # 2026-08-29 geaendert. "ganze" steht seither auf Rang 98. Die
        # positive Klasse bleibt, sie wird nur nicht mehr aus einer
        # sortierungsabhaengigen Stichprobe gezogen.
        treffer = [z for z in ergebnis["rows"] if z["word"] == "ganze"]
        assert treffer, "Zeuge fehlt, die Probe waere leer"
        # Unter Paarsemantik trug "ganze" f=14 bei Korpusfrequenz 13, und
        # genau dieser UEBERSCHUSS war hier die positive Klasse. Seit der
        # Umstellung auf Everts Distanztafel zaehlt die Vereinigung: f=10,
        # und die beiden Zaehlschemata stimmen wieder ueberein. Der Test
        # prueft jetzt das, was die Umstellung leisten sollte.
        assert treffer[0]["f"] == 10
        korpus = tw.query_count_tool(query="ganze").get("total")
        assert korpus == 13
        assert treffer[0]["f"] <= korpus


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestWerkzeug:
    def test_referenz_ist_das_korpus_ohne_das_fenster(self, active_index):  # noqa: F811
        r = tw.keyness_tool(
            target_context_query='cql:[word="die"]', context_window=5, min_freq=5
        )
        diag = r["diagnostics"]
        assert diag["reference_kind"] == "rest_des_korpus_ohne_kontext"
        gesamt = int(active_index.fast_index.lexicons.word.total_tokens)
        # Seit dem 2026-09-01 stehen ZWEI Zerlegungen nebeneinander.
        #
        # Die ROHE geht weiterhin genau auf: Fenster plus Rest ist das
        # ganze Korpus. Sie steht in den _roh-Feldern.
        assert diag["target_tokens_roh"] + diag["reference_tokens_roh"] == gesamt
        # Die GERECHNETE ist kleiner, weil der Zaehler gefiltert ist und
        # der Nenner deshalb aus demselben gefilterten Bestand kommt. Wer
        # hier die rohe Summe erwartet, erwartet einen gespaltenen Nenner.
        assert diag["target_tokens"] <= diag["target_tokens_roh"]
        assert diag["reference_tokens"] <= diag["reference_tokens_roh"]
        assert diag["target_tokens"] > 0 and diag["reference_tokens"] > 0
        assert diag["node_hits"] > 0
        assert diag["context_window"] == 5
        # Die Zerlegung des ROHEN Fensters ist offengelegt.
        assert (
            diag["target_tokens_roh"] + diag["unlabelled_positions"]
            == diag["context_positions"]
        )

    def test_der_knoten_fuehrt_die_liste_nicht_mehr_an(self, active_index):  # noqa: F811
        """Der schwerste Einzelschaden der Vorfassung, als Zahl.

        Mit dem inklusiven Lesen stand 'die' auf Rang 1 mit log_ratio 8,81.
        Wahr sind 161 Kontextvorkommen gegen 867 ausserhalb.

        BENCH-ANKER: 161 und 867 sind Zahlen des Testindex, auf den die
        Suite festgelegt ist. Genau diese Genauigkeit ist der Zweck des
        Tests, deshalb wird er nicht auf einen beliebigen Index
        verallgemeinert. Auf einem anderen Korpus schlaegt er fehl, ohne
        dass etwas kaputt waere. Die indexunabhaengigen Invarianten stehen
        in TestLrcAmEchtenIndex und laufen auf jedem Korpus.
        """
        r = tw.keyness_tool(
            target_context_query='cql:[word="die"]', context_window=5, min_freq=0
        )
        zeile = next((z for z in r["rows"] if z["word"] == "die"), None)
        assert zeile is not None
        assert zeile["target_freq"] == 161, zeile["target_freq"]
        assert abs(zeile["log_ratio"]) < 1.0, zeile["log_ratio"]

    def test_mischung_mit_docsets_ist_ein_fehler(self, active_index):  # noqa: F811
        with pytest.raises(tw.ToolInputError):
            tw.keyness_tool(
                target_context_query='cql:[word="die"]', target=["a"], reference=["b"]
            )

    def test_lemma_attribut_wird_gemeldet(self, active_index):  # noqa: F811
        r = tw.keyness_tool(
            target_context_query='cql:[word="die"]', attribute="lemma", min_freq=5
        )
        assert r["diagnostics"]["attribute"] == "lemma"

    def test_unbekannter_knoten_ist_ein_ehrlicher_fehler(self, active_index):  # noqa: F811
        with pytest.raises(tw.ToolInputError) as fehler:
            tw.keyness_tool(target_context_query='cql:[word="gibtesnicht12345"]')
        assert "kommt nicht vor" in str(fehler.value)


class TestVertrag:
    def test_schema_deklariert_die_neuen_felder(self):
        diag = tw.KEYNESS_RESPONSE["properties"]["diagnostics"]["properties"]
        for feld in (
            "node_hits", "context_window", "attribute",
            "context_positions", "unlabelled_positions",
        ):
            assert feld in diag, feld
        params = tw.KEYNESS_TOOL["function"]["parameters"]["properties"]
        for feld in ("target_context_query", "context_window", "attribute"):
            assert feld in params, feld
            assert feld in tw.KEYNESS_TOOL["schema"]["properties"], feld

    def test_prompt_nennt_das_eigene_intervall(self):
        from candyconc.candyconc_copilot import prompts as P

        doc = " ".join(P.TOOLS_DOC.split())
        assert "EIGENEN Intervalls" in doc
        assert "NICHT der 95%-CI" in doc


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestLrcAmEchtenIndex:
    """A6: die Statistik gegen echte Knoten, nicht gegen erfundene Zellen.

    Synthetische Zellen beweisen die Formel. Sie beweisen nicht, dass die
    Zaehlung darunter stimmt. Diese Proben laufen ueber echte Knoten mit
    echten Korpusfrequenzen und pruefen die Invarianten, die nur dort
    brechen koennen.

    Am 273M-Korpus durchgelaufen bis hinauf zu ``[pos="NOUN"]`` mit
    46.977.338 Ankern und 83.056.089 Kontextpositionen.
    """

    #: Fenster, nicht Knoten. Der Knoten kommt aus dem Index selbst, sonst
    #: haengt die Probe daran, ob ein ausgedachtes Wort dort vorkommt, und
    #: ueberspringt sich still auf jedem anderen Korpus. Ein Skip-Pfad ist
    #: Verhalten, kein gruener Test.
    FENSTER = ((5, 5), (3, 7), (10, 10))

    #: Obergrenze der Knotenfrequenz. Die unabhaengige Gegenrechnung holt
    #: die Treffer selbst und kappt bei fuenf Millionen. Am 273M-Korpus
    #: liegen die haeufigsten Woerter darueber ("der" 8.402.304, "die"
    #: 6.836.440, "und" 5.456.715), die Gegenrechnung waere dann gekappt
    #: und die Probe verglichen eine vollstaendige mit einer
    #: unvollstaendigen Zahl. Ein gedeckelter Knoten ist genauso echt und
    #: kostet Sekunden statt Minuten.
    MAX_KNOTENFREQUENZ = 20_000

    @classmethod
    def _haeufiger_knoten(cls, backend, rang: int = 0) -> str:
        """Das ``rang``-haeufigste alphabetische Wort unter der Obergrenze."""
        import numpy as _np

        lex = backend.lexicons.word
        ids = _np.arange(1, int(lex.vocab_size), dtype=_np.int64)
        freqs = _np.asarray(lex.get_freqs_for_ids(ids), dtype=_np.int64)
        namen = list(lex.get_strings_for_ids(ids))
        gefunden = []
        for i in _np.argsort(-freqs):
            wort = str(namen[i])
            if not (wort.isalpha() and len(wort) > 1):
                continue
            if int(freqs[i]) > cls.MAX_KNOTENFREQUENZ:
                continue
            gefunden.append(wort)
            if len(gefunden) > rang:
                break
        assert gefunden, "Index ohne brauchbare Knoten: Probe unmoeglich"
        return gefunden[min(rang, len(gefunden) - 1)]

    def _tabelle(self, backend, query, wl, wr):
        import numpy as _np
        from candyconc.services.tools.keyness import keyness_full_stats

        freq, positionen, _tr, ohne = context_token_counts(
            backend, query, window_left=wl, window_right=wr, attribute="word"
        )
        lex = backend.lexicons.word
        gesamt = int(backend.token_store.token_count)
        namen = list(freq)
        if not namen:
            return None
        a = _np.array([freq[w] for w in namen], dtype=_np.float64)
        ids = _np.array([int(lex.get_id(w)) for w in namen], dtype=_np.int64)
        korpus = _np.where(
            ids > 0, lex.get_freqs_for_ids(_np.maximum(ids, 1)), 0
        ).astype(_np.float64)
        c = _np.clip(korpus - a, 0, None)
        n1 = positionen - ohne
        return keyness_full_stats(a, c, n1, gesamt - n1), a, c, namen

    @pytest.mark.parametrize("rang,fenster", list(enumerate(FENSTER)))
    def test_die_invarianten_halten_auf_echten_knoten(
        self, active_index, rang, fenster
    ):  # noqa: F811
        import numpy as _np

        backend = active_index.fast_index
        wl, wr = fenster
        query = 'cql:[word="%s"]' % self._haeufiger_knoten(backend, rang)
        ergebnis = self._tabelle(backend, query, wl, wr)
        assert ergebnis is not None, "%s liefert keinen Kontext" % query
        out, a, c, namen = ergebnis

        assert _np.all(_np.isfinite(out["lrc"])), "lrc traegt NaN oder Unendlich"
        verstoss = _np.abs(out["lrc"]) > _np.abs(out["log_ratio"]) + 1e-9
        assert not verstoss.any(), (
            "lrc groesser als log_ratio bei %s"
            % [namen[i] for i in _np.flatnonzero(verstoss)[:5]]
        )
        nz = out["lrc"] != 0
        assert _np.all(
            _np.sign(out["lrc"][nz]) == _np.sign(out["log_ratio"][nz])
        ), "Vorzeichen von lrc und log_ratio widersprechen sich"

    @pytest.mark.parametrize("rang,fenster", list(enumerate(FENSTER)))
    def test_der_konservative_wert_liegt_nie_weiter_aussen(
        self, active_index, rang, fenster
    ):  # noqa: F811
        """Zwei Angaben mit verschiedenen Niveaus, eine erlaubte Richtung.

        ``log_ratio_ci_low/high`` steht auf 0,05, ``lrc`` auf ``0,001/n``.
        Die strengere Schranke muss NAEHER an null liegen, sonst ist eine
        der beiden Angaben falsch und die Tabelle unlesbar.
        """
        import numpy as _np

        backend = active_index.fast_index
        wl, wr = fenster
        query = 'cql:[word="%s"]' % self._haeufiger_knoten(backend, rang)
        ergebnis = self._tabelle(backend, query, wl, wr)
        assert ergebnis is not None, "%s liefert keinen Kontext" % query
        out, _a, _c, _namen = ergebnis

        pos = out["lrc"] > 0
        assert pos.any(), "keine positive Klasse, die Probe beweist nichts"
        assert _np.all(out["lrc"][pos] <= out["log_ratio_ci_low"][pos] + 1e-9)
        neg = out["lrc"] < 0
        if neg.any():
            assert _np.all(out["lrc"][neg] >= out["log_ratio_ci_high"][neg] - 1e-9)

    @pytest.mark.parametrize("rang,fenster", list(enumerate(FENSTER)))
    def test_keine_kontextzahl_uebersteigt_die_korpusfrequenz(
        self, active_index, rang, fenster
    ):  # noqa: F811
        """Der Fehler, der die Keyness am staerksten verzerrt.

        Zaehlt ein Typ im Kontext haeufiger als im ganzen Korpus, ist die
        Referenzzelle negativ und jede Effektstaerke Unsinn.
        """
        import numpy as _np

        backend = active_index.fast_index
        wl, wr = fenster
        query = 'cql:[word="%s"]' % self._haeufiger_knoten(backend, rang)
        freq, _pos, _tr, _ohne = context_token_counts(
            backend, query, window_left=wl, window_right=wr, attribute="word"
        )
        assert freq, "%s liefert keinen Kontext" % query
        lex = backend.lexicons.word
        schlimmste = []
        for wort, zahl in freq.items():
            wid = int(lex.get_id(wort))
            if wid <= 0:
                continue
            korpus = int(lex.get_freqs_for_ids(_np.array([wid], dtype=_np.int64))[0])
            if zahl > korpus:
                schlimmste.append((wort, zahl, korpus))
        assert not schlimmste, "Kontextzahl ueber Korpusfrequenz: %s" % schlimmste[:5]
