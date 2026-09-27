"""Acht Befunde des adversarialen Gates ueber Commit f2c0139bd1.

Vier davon waren blockierend, und drei entstanden erst durch die
Reparaturen dieser Kampagne. Jeder ist hier an der Naht gepinnt, an der er
sichtbar wurde, nicht an der, an der er bequem zu pruefen waere.

A. Das response_model streicht die Kappungsfelder
   DocsetFromSearchResponse fuehrte fuenf Felder und kein
   model_config extra=allow. truncated, scan_limit und truncation_note
   starben in pydantic, und die HTTP-Antwort auf limit=100 war byte-gleich
   zu der ohne jede Meldung. Ein Feld, das im Response-Modell verloren
   geht, zaehlt nicht.

B. Der neue ValueError wurde HTTP 500
   compute_keyness wirft seit aee3bde7b4 bei pos ohne pos_map. Die Route
   fing ihn nicht: eine Eingabefrage der Aufruferin kam als Serverfehler
   zurueck, mit verschluckter Meldung. Der Copilot-Wrapper reichte ihn
   ebenfalls roh durch statt als ToolInputError.

C. Die Kappungsmeldung war im Klartext-Zweig ein Falschalarm
   "und" mit limit=100 lieferte 919 gescannte Treffer und dieselben 741
   Dokumente wie ungedeckelt, und die Bedingung "gescannt >= limit"
   behauptete dort eine Kappung, die nicht stattgefunden hat.

D. Drei Landungen umgingen den Chokepoint
   orchestrator.py gab bei CLARIFY, bei der ACTION-Freigabe und im
   Plan-Gate "cleaned_content" ROH zurueck, also Modelltext ohne
   Zitatwache und ohne Politur, waehrend der Docstring des Chokepoints
   "egal ueber welche Landung" verspricht. Einwand 1 war damit an EINER
   von zwei Nahtstellen geschlossen: die Rueckfrage aus dem KONTRAKT war
   gedeckt, die aus dem CONTROL-FRAME nicht.

E. Die letzte Maskenstelle entschied weiter je Satz
   _sequence_postings_partitioned prueft die Maske je SEGMENT ueber
   sent_to_doc und verwarf den ganzen Satzblock.

F. Der Copilot-Zweig meldete die Kappung nicht
   create_docset_tool reichte kein bericht durch: REST meldete, der
   Copilot schwieg.

G. Die Idempotenzwache verschluckte den ganzen Steckbrief
   Sie prueft ANY. Eine einzige uebereinstimmende Zeile liess den GANZEN
   Anhang entfallen, samt Indexstand.

H. Der Indexstand nannte den Default-Korpus
   Der Rueckfall fragte get_corpus(None), waehrend der Docstring
   verspricht, der Wert stamme von dem Index, auf dem gerechnet wurde.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_WURZEL = Path(__file__).resolve().parents[2]

_braucht_index = pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from candyconc.services.backend.server import app

    return TestClient(app)


@_braucht_index
class TestA_KappungsfelderErreichenDenClient:
    def test_gekappt_meldet_sich_in_der_http_antwort(self, client):
        r = client.post("/api/v1/analysis/docset_from_search",
                        json={"query": 'cql:[pos="NOUN"]', "limit": 100})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("truncated") is True, d
        assert d.get("scan_limit") == 100
        # "Präfix" mit Umlaut. Der Text ist am 2026-09-01 aus der
        # ASCII-Umschrift geholt worden, weil er dem Nutzer angezeigt wird
        # und die Umschrift mehrfach beanstandet war. Die Probe haelt die
        # AUSSAGE fest, nicht die alte Schreibung.
        assert "Präfix" in str(d.get("truncation_note") or "")

    def test_ohne_deckel_KEINE_meldung(self, client):
        r = client.post("/api/v1/analysis/docset_from_search",
                        json={"query": 'cql:[pos="NOUN"]'})
        d = r.json()
        assert d.get("truncated") in (None, False), d
        # Und das Ergebnis ist wirklich groesser als das gekappte.
        assert d["doc_count"] > 100

    def test_der_klartext_zweig_meldet_KEINEN_falschalarm(self, client):
        """Befund C. 919 gescannte Treffer bei limit=100, aber nichts gekappt."""
        gekappt = client.post("/api/v1/analysis/docset_from_search",
                              json={"query": "und", "limit": 100}).json()
        ganz = client.post("/api/v1/analysis/docset_from_search",
                           json={"query": "und"}).json()
        assert gekappt["doc_count"] == ganz["doc_count"], (
            "der Klartext-Zweig kappt gar nicht"
        )
        assert gekappt.get("truncated") in (None, False), gekappt


@_braucht_index
class TestB_EingabefrageIstKeinServerfehler:
    def test_pos_ohne_karte_ist_422_nicht_500(self, client):
        r = client.post("/api/v1/analysis/keyness",
                        json={"target": ["a", "a"], "reference": ["b"],
                              "pos": "NOUN"})
        assert r.status_code == 422, (r.status_code, r.text[:200])
        assert "pos_map" in r.text

    def test_gueltige_anfrage_bleibt_200(self, client):
        r = client.post("/api/v1/analysis/keyness",
                        json={"target": ["Hund", "Hund"], "reference": ["Katze"],
                              "pos": "NOUN",
                              "pos_map": {"Hund": "NOUN", "Katze": "NOUN"}})
        assert r.status_code == 200, r.text[:200]


class TestD_KeineLandungAmChokepointVorbei:
    """Gepinnt am Quelltext, weil die Landungen Zustandswechsel sind.

    Der Verhaltensnachweis steht daneben: derselbe Text durch
    politur_mit_zitatwache verliert das Fabrikat.
    """

    @staticmethod
    def _quelle() -> str:
        return (_WURZEL / "src" / "candyconc" / "candyconc_copilot"
                / "orchestrator.py").read_text(encoding="utf-8")

    def test_kein_roher_rueckgabewert_von_modelltext(self):
        """Ueber den AST, nicht ueber die Schreibweise.

        Die Vorfassung suchte den Regex
        ``\n\s+return cleaned_content(?: or "")?\s*\n`` und verlangte
        Zeilenende direkt hinter dem Namen. Fuenf Gestalten desselben
        Defekts liefen daran vorbei, jede davon eine ungedeckte Landung::

            return cleaned_content.strip()
            return str(cleaned_content)
            return cleaned_content or None
            antwort = cleaned_content; return antwort
            return cleaned_content  # Kommentar

        Schon ein nachgestellter Kommentar entzog den Defekt der Messung.
        Diese Fassung fragt den Syntaxbaum: kommt der Name in IRGENDEINEM
        return-Ausdruck vor, direkt oder ueber eine Zwischenvariable?
        """
        import ast

        baum = ast.parse(self._quelle())

        def _nennt(knoten) -> bool:
            return any(
                isinstance(n, ast.Name) and n.id == "cleaned_content"
                for n in ast.walk(knoten)
            )

        # Die Landungen, die den Modelltext BEWACHT weitergeben. Wer
        # cleaned_content an eine davon uebergibt, gibt ihn nicht roh
        # zurueck -- die erste Fassung dieser Pruefung hat genau das
        # verwechselt und vier korrekte Stellen gemeldet.
        BEWACHT = {
            "politur_mit_zitatwache",
            "_ra_pause_turn",
            "_ra_finish_turn",
        }

        def _rufname(aufruf) -> str:
            f = aufruf.func
            return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")

        def _ist_bewachte_uebergabe(wert) -> bool:
            """Liegt JEDES Vorkommen des Namens in den Argumenten einer Wache?

            Nicht nur die aeusserste Ebene: die echte Landung lautet
            ``return politur_mit_zitatwache(...)[0]``, also ein Index um
            den Aufruf. Eine Pruefung, die nur den obersten Knoten ansieht,
            haette sie faelschlich gemeldet.
            """
            eltern = {}
            for knoten in ast.walk(wert):
                for kind in ast.iter_child_nodes(knoten):
                    eltern[kind] = knoten
            vorkommen = [
                n for n in ast.walk(wert)
                if isinstance(n, ast.Name) and n.id == "cleaned_content"
            ]
            if not vorkommen:
                return True
            for n in vorkommen:
                kette = []
                k = n
                while k in eltern:
                    k = eltern[k]
                    kette.append(k)
                if not any(
                    isinstance(a, ast.Call) and _rufname(a) in BEWACHT for a in kette
                ):
                    return False
            return True

        roh: list[str] = []
        for funktion in ast.walk(baum):
            if not isinstance(funktion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Zwischenvariablen, die DIREKT aus cleaned_content stammen.
            durchgereicht = {
                ziel.id
                for knoten in ast.walk(funktion)
                if isinstance(knoten, ast.Assign)
                and isinstance(knoten.value, ast.Name)
                and knoten.value.id == "cleaned_content"
                for ziel in knoten.targets
                if isinstance(ziel, ast.Name)
            }
            for knoten in ast.walk(funktion):
                if not isinstance(knoten, ast.Return) or knoten.value is None:
                    continue
                # Reihenfolge: erst fragen, OB der Name vorkommt. Die
                # Wach-Pruefung meldet "bewacht" auch fuer Ausdruecke ohne
                # jedes Vorkommen, und damit uebersprang eine Vorfassung
                # die Zwischenvariablen-Gestalt (``antwort =
                # cleaned_content; return antwort``) noch immer.
                if _nennt(knoten.value):
                    if not _ist_bewachte_uebergabe(knoten.value):
                        roh.append(f"{funktion.name}:{knoten.lineno} direkt")
                    continue
                if any(
                    isinstance(n, ast.Name) and n.id in durchgereicht
                    for n in ast.walk(knoten.value)
                ):
                    roh.append(f"{funktion.name}:{knoten.lineno} ueber Zwischenvariable")
        assert roh == [], f"ungedeckte Landung(en): {roh}"

    def test_die_pausierende_landung_fuehrt_die_wache(self):
        quelle = self._quelle()
        i = quelle.index("def _ra_pause_turn(")
        rumpf = quelle[i: quelle.index("\n    @staticmethod", i)]
        assert "politur_mit_zitatwache" in rumpf
        # Der geprueste Text geht in die Session UND an den Aufrufer.
        assert "content\": geprueft" in rumpf
        assert "return geprueft" in rumpf

    def test_das_fabrikat_ueberlebt_die_wache_nicht(self):
        """Exercise quote verification with the unsupported quotation fixture."""
        from candyconc.candyconc_copilot import recipe_runtime as rr

        fabrikat = ("der jungen Maenner sind keine Fluechtlinge. "
                    "Sie sind ruecksichtslose Invasoren.")
        text = f'Zwischenstand: Im Korpus steht die Passage "{fabrikat}".'
        # `tool` produktivtreu (orchestrator.py:6997 legt to_dict() ab):
        # die Wache entscheidet nach Herkunft, und eine Attrappe ohne
        # Werkzeugnamen haette den Produktivpfad nicht abgebildet. MIT
        # Evidenz ist der Test zudem schaerfer: das Fabrikat muss auch dann
        # fallen, wenn echte Belegzeilen vorliegen.
        evidenz = [{"tool": "document_search",
                    "grounding_surface": ["Die Abgeordnete sprach ueber Flucht."]}]
        geprueft, _ = rr.politur_mit_zitatwache(text, evidenz)
        assert "Invasoren" in text
        assert "Invasoren" not in geprueft


class TestE_KeineMaskeMehrUeberDenSatz:
    """Die Docset-Maske entscheidet je TREFFERPOSITION, nicht je Satz.

    Die Vorfassung dieses Tests war ein DATEIWEITER Quelltextbann: sie
    filterte alle Zeilen aus ``src/cqlhpc/engine.py``, die ``sent_to_doc``
    enthalten, und verlangte die leere Liste. Die Maskenentscheidung selbst
    hat sie nie gemessen. Verschiebt jemand sie in ein Hilfsmodul, bleibt
    ``engine.py`` sauber und der Test gruen. Eine Codezeile mit angehaengtem
    ``Verweis`` in doppelten Backticks fiel ausserdem aus dem Filter.

    Der Vertrag wird am VERHALTEN gehalten, in
    ``tests/core/test_docset_mask_per_position.py``, und dort mit vier
    Messungen am echten Index::

        test_die_positive_klasse_existiert_ueberhaupt
        test_zwei_komplementaere_masken_partitionieren_exakt
        test_doc_id_ist_das_dokument_das_die_position_enthaelt
        test_die_zuschreibung_am_bench_index

    Der erste haelt ausdruecklich fest, dass es satzuebergreifende
    Dokumentgrenzen ueberhaupt gibt -- ohne sie pruefte die Partition
    nichts. Ein Quelltextbann daneben haette nur Sicherheit vorgetaeuscht,
    die er nicht traegt.
    """

    def test_die_verhaltensdeckung_existiert_und_laeuft(self):
        """Kein Ersatz fuer die Messung, sondern ihr Nachweis.

        Wuerde die Verhaltensdatei geloescht oder umbenannt, faellt der
        Vertrag lautlos weg. Dieser Test haelt fest, DASS sie existiert und
        die vier Messungen fuehrt.
        """
        datei = _WURZEL / "tests" / "core" / "test_docset_mask_per_position.py"
        assert datei.exists(), datei
        quelle = datei.read_text(encoding="utf-8")
        for name in (
            "test_die_positive_klasse_existiert_ueberhaupt",
            "test_zwei_komplementaere_masken_partitionieren_exakt",
            "test_doc_id_ist_das_dokument_das_die_position_enthaelt",
            "test_die_zuschreibung_am_bench_index",
        ):
            assert f"def {name}(" in quelle, name


@_braucht_index
class TestF_DerCopilotMeldetDieKappungAuch:
    def test_create_docset_tool_reicht_den_bericht_durch(self):
        quelle = (_WURZEL / "src" / "candyconc" / "candyconc_copilot"
                  / "tool_wrappers.py").read_text(encoding="utf-8")
        i = quelle.index("_search_docset_doc_ids,")
        assert "bericht=" in quelle[i: i + 500], (
            "der Copilot-Zweig ruft ohne Ausgabefach: dieselbe Kappung "
            "bleibt dort still, waehrend REST sie meldet"
        )


@_braucht_index
class TestGH_SteckbriefUndIndexstand:
    """G und H, ueber einen sauberen Unterprozess (conftest stubbt Copilot)."""

    @staticmethod
    def _lauf(skript: str) -> dict:
        import json
        import subprocess
        import sys

        voll = (f"import sys, json\nsys.path.insert(0, {str(_WURZEL / 'src')!r})\n"
                + skript)
        r = subprocess.run([sys.executable, "-c", voll], capture_output=True,
                           text=True, cwd=str(_WURZEL), timeout=600,
                           env={**os.environ, "CANDYCONC_INDEX_PATH": _BENCH})
        # A failed measurement must fail the assertion rather than become a skip.
        assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, (
            f"Messlauf gescheitert (rc={r.returncode}): {r.stderr[-600:]}")
        return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])

    def test_eine_zufaellig_gleiche_zeile_verschluckt_nicht_alles(self):
        """Befund G: die Pruefung lief ueber ANY."""
        ergebnis = self._lauf(
            "from candyconc.services.backend import server as srv\n"
            "from candyconc.candyconc_copilot import query_runtime as qr\n"
            "from candyconc.candyconc_copilot import recipe_runtime as rr\n"
            "from candyconc.candyconc_copilot import tool_wrappers as tw\n"
            "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
            "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
            "out = tw.query_count_tool(query='und')\n"
            "p = [make_evidence_item(\n"
            "    item_id='e', tool='query_count', tool_call_id='c',\n"
            "    query={'query': 'und'}, output=out, analysis_family='x')]\n"
            "voll = rr.methodensteckbrief_anhaengen('Befund.', p)\n"
            "zeile = [z[2:] for z in voll.splitlines() if z.startswith('- ')][0]\n"
            "mit = rr.methodensteckbrief_anhaengen('Befund. ' + zeile, p)\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'voll_hat_indexstand': 'Indexstand' in voll,\n"
            "  'mit_hat_indexstand': 'Indexstand' in mit,\n"
            "  'mit_hat_ueberschrift': rr.METHODENSTECKBRIEF_UEBERSCHRIFT in mit}))\n"
        )
        assert ergebnis["voll_hat_indexstand"] is True
        assert ergebnis["mit_hat_indexstand"] is True, (
            "eine einzige uebereinstimmende Zeile hat den GANZEN Anhang "
            "entfallen lassen, samt Indexstand"
        )
        assert ergebnis["mit_hat_ueberschrift"] is True

    def test_der_indexstand_folgt_dem_gemessenen_korpus(self):
        """Befund H, am VERHALTEN statt am Quelltext.

        Die Vorfassung las den Rumpf von ``_indexstand_zeile`` und suchte
        nach ``corpus_id`` und dem Fehlen von ``get_corpus(None)``. Das
        misst, was jemand hingeschrieben hat. Geprueft wird jetzt der
        Unterschied, den die Reparatur macht: nennt die Evidenz einen
        Korpus, den der Server nicht aufloesen kann, entsteht KEINE
        Indexstand-Zeile, statt den Stand des voreingestellten Index zu
        nennen, der an der Messung nicht beteiligt war.
        """
        ergebnis = self._lauf(
            "from candyconc.services.backend import server as srv\n"
            "from candyconc.candyconc_copilot import query_runtime as qr\n"
            "from candyconc.candyconc_copilot import recipe_runtime as rr\n"
            "from candyconc.candyconc_copilot import tool_wrappers as tw\n"
            "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
            "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
            "out = tw.query_count_tool(query='und')\n"
            "def steckbrief(corpus_id):\n"
            "    o = dict(out)\n"
            "    if corpus_id is None:\n"
            "        o.pop('scope', None)\n"
            "    else:\n"
            "        o['scope'] = dict(o.get('scope') or {}, corpus_id=corpus_id)\n"
            "    p = [make_evidence_item(item_id='e', tool='query_count',\n"
            "         tool_call_id='c', query={'query':'und'}, output=o,\n"
            "         analysis_family='x')]\n"
            "    return rr.methodensteckbrief_anhaengen('Befund.', p)\n"
            "eigen = steckbrief(None)\n"
            "fremd = steckbrief('gibtsnichtxyz-korpus')\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'eigen_hat_stand': 'Indexstand' in eigen,\n"
            "  'fremd_hat_stand': 'Indexstand' in fremd,\n"
            "  'fremd_hat_steckbrief': rr.METHODENSTECKBRIEF_UEBERSCHRIFT in fremd}))\n"
        )
        assert ergebnis["eigen_hat_stand"] is True, ergebnis
        assert ergebnis["fremd_hat_stand"] is False, (
            "der Steckbrief nennt den Stand eines Index, der an der "
            "Messung nicht beteiligt war")
        # Und der uebrige Steckbrief bleibt: die Zeile entfaellt, nicht alles.
        assert ergebnis["fremd_hat_steckbrief"] is True, ergebnis



@_braucht_index
class TestI_KeinBetreiberpfadImEreignisstrom:
    """Der letzte ernste Befund des Gates.

    build_method_block fuehrt den Indexstand als
    ``<absoluter Pfad>@<mtime_ns>``. Die ROHE Werkzeugausgabe speist im
    Orchestrator drei Verbraucher aus EINER Variablen: den Evidenzposten,
    das SSE-Ereignis copilot.tool_result und das Lineage-Log ueber
    project.add_ai_output. Gehasht wurde nur der erste, und das
    Heimatverzeichnis des Betreibers stand weiter im Ereignisstrom und im
    Projektprotokoll.

    Gehasht wird jetzt an der Stelle, an der die Ausgabe entsteht: ein
    Aufruf deckt alle drei. NICHT in build_method_block selbst, weil die
    REST-Provenienz die volle Signatur fuehrt und
    tests/backend/test_provenance_r7.py sie dort woertlich pinnt
    ("idx@123"). Dieser korrekte Test bleibt unangetastet.

    NACHTRAG: der Pfad entsteht inzwischen gar nicht mehr. Die REST-Naht
    fuehrte denselben Indexstand weiter im Klartext, und damit stand das
    Heimatverzeichnis in jeder Analyse-Antwort und in der Kopfzeile jedes
    Exports. Gehasht wird deshalb jetzt in
    ``routes/analysis._index_fingerprint``, der gemeinsamen Quelle beider
    Naehte, ueber ``analysis_defaults.kurzer_indexstand``.

    Dieser Test hat das selbst gemeldet: seine Zusicherung "die positive
    Klasse fehlt, dann prueft dieser Test nichts" schlug an, sobald die
    ROHE Ausgabe keinen Pfad mehr trug. Er prueft seither BEIDES: dass die
    echte Ausgabe schon an der Quelle sauber ist, und dass die Wache ihre
    Arbeit weiter tut, gemessen an einer synthetischen Ausgabe MIT Pfad.
    Ohne diesen zweiten Teil waere die Wache ungeprueft, sobald ein
    kuenftiger Produzent die Signatur wieder roh setzt.
    """

    @staticmethod
    def _lauf() -> dict:
        import json
        import subprocess
        import sys

        skript = (
            f"import sys, os, json\nsys.path.insert(0, {str(_WURZEL / 'src')!r})\n"
            "from candyconc.services.backend import server as srv\n"
            "from candyconc.candyconc_copilot import query_runtime as qr\n"
            "from candyconc.candyconc_copilot import tool_wrappers as tw\n"
            "from candyconc.candyconc_copilot.analysis_grounding import (\n"
            "    werkzeugausgabe_ohne_betreiberpfad as scrub)\n"
            "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
            "heim = os.path.expanduser('~')\n"
            "out = tw.trend_analysis_tool(date_field='split', query='und')\n"
            "sauber = scrub(out)\n"
            # Die positive Klasse fuer die WACHE: eine Ausgabe, die den Pfad
            # wirklich traegt. Die echte traegt ihn nicht mehr, weil an der
            # Quelle gehasht wird, und dann pruefte scrub() an ihr nichts.
            "roh_synth = {'rows': [{'kw': 'und'}],\n"
            "  'method': {'family': 'trend',\n"
            "             'indexFingerprint': heim + '/runtime/idx@1780',\n"
            "             'index_fingerprint': heim + '/runtime/idx@1780'}}\n"
            "synth = scrub(roh_synth)\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'roh_hat_pfad': heim in json.dumps(out),\n"
            "  'sauber_hat_pfad': heim in json.dumps(sauber),\n"
            "  'stand': (sauber.get('method') or {}).get('index_fingerprint',\n"
            "           (sauber.get('method') or {}).get('indexFingerprint', '')),\n"
            "  'synth_roh_hat_pfad': heim in json.dumps(roh_synth),\n"
            "  'synth_sauber_hat_pfad': heim in json.dumps(synth),\n"
            "  'synth_stand': (synth.get('method') or {}).get('indexFingerprint', ''),\n"
            "  'synth_rest_unveraendert': {k: v for k, v in synth.items() if k != 'method'}\n"
            "                             == {k: v for k, v in roh_synth.items() if k != 'method'},\n"
            "  'rest_unveraendert': {k: v for k, v in sauber.items() if k != 'method'}\n"
            "                       == {k: v for k, v in out.items() if k != 'method'}}))\n"
        )
        r = subprocess.run([sys.executable, "-c", skript], capture_output=True,
                           text=True, cwd=str(_WURZEL), timeout=600,
                           env={**os.environ, "CANDYCONC_INDEX_PATH": _BENCH})
        # A failed measurement must fail the assertion rather than become a skip.
        assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, (
            f"Messlauf gescheitert (rc={r.returncode}): {r.stderr[-600:]}")
        return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])

    def test_der_pfad_entsteht_schon_an_der_quelle_nicht(self):
        # Die staerkere Aussage: die ROHE Werkzeugausgabe traegt ihn nicht
        # mehr, weil _index_fingerprint hasht, bevor der Wert je in einen
        # method-Block kommt.
        e = self._lauf()
        assert e["roh_hat_pfad"] is False, e
        assert e["sauber_hat_pfad"] is False, e
        assert re.fullmatch(r"[0-9a-f]{12}", str(e["stand"])), e["stand"]

    def test_die_wache_wirkt_weiter_auf_eine_ausgabe_MIT_pfad(self):
        # Die positive Klasse. Setzt ein kuenftiger Produzent die Signatur
        # wieder roh, faengt die Wache sie weiterhin ab.
        e = self._lauf()
        assert e["synth_roh_hat_pfad"] is True, (
            "die positive Klasse fehlt: die synthetische Ausgabe traegt "
            "keinen Pfad, dann prueft dieser Test nichts")
        assert e["synth_sauber_hat_pfad"] is False, e
        assert re.fullmatch(r"[0-9a-f]{12}", str(e["synth_stand"])), e["synth_stand"]

    def test_nur_der_indexstand_wird_angefasst(self):
        e = self._lauf()
        assert e["rest_unveraendert"] is True, e
        assert e["synth_rest_unveraendert"] is True, e

    @staticmethod
    def _verbraucher_messen() -> dict:
        """Alle drei Verbraucher am laufenden Orchestrator abgreifen.

        Die Vorfassung war ein GREP: sie suchte die Position des
        Wache-Aufrufs im Quelltext und pruefte, ob drei
        Verbraucher-Zeichenketten IRGENDWO danach stehen. Damit mass sie
        Textposition, nicht Datenfluss. Zwei Mutationen, die die Wache
        nachweislich wirkungslos machen, liessen sie gruen:

            M1  Wache laeuft, ihr Ergebnis wird sofort ueberschrieben
            M2  Wache schreibt auf eine Wegwerfvariable, `out` bleibt roh

        Diese Fassung faehrt einen echten Turn und liest, was bei den drei
        Verbrauchern WIRKLICH ankommt.
        """
        import json
        import os
        import subprocess
        import sys

        skript = (
            "import sys, json, os, asyncio; sys.path.insert(0,'src')\n"
            "from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator\n"
            "HEIM = os.path.expanduser('~')\n"
            "ROH = HEIM + '/runtime/bench@1780992164997579395'\n"
            "ereignisse = []\n"
            "class Bus:\n"
            "    def publish(self, event, session_id=None): ereignisse.append(event)\n"
            "lineage = []\n"
            "class Projekt:\n"
            "    def add_ai_output(self, s): lineage.append(s)\n"
            "    def __getattr__(self, n): return lambda *a, **k: None\n"
            "gerufen = []\n"
            "def call_llm(messages, exposed_tools=None, stream=None, user=None, policy=None, **kw):\n"
            "    hat_tool = any(m.get('role') == 'tool' for m in messages)\n"
            "    if not hat_tool:\n"
            "        return {'choices': [{'message': {'role':'assistant','tool_calls': [{\n"
            "            'id':'c1','type':'function','function': {'name':'run_cqlf_query',\n"
            "            'arguments': json.dumps({'query':'und'})}}]},\n"
            "            'finish_reason':'tool_calls'}],\n"
            "            '_cc_route':'chat:kwic', '_cc_model':'m'}\n"
            "    return {'choices': [{'message': {'role':'assistant',\n"
            "        'content':'Es gibt 1 Treffer.'}, 'finish_reason':'stop'}],\n"
            "        '_cc_route':'chat:kwic-final', '_cc_model':'m'}\n"
            "async def dispatch(tool_call, _token=None):\n"
            "    gerufen.append(1)\n"
            "    return {'status':'success','total':1,\n"
            "            'rows':[{'left':'a','kw':'und','right':'b'}],\n"
            "            'method': {'indexFingerprint': ROH, 'index_fingerprint': ROH}}\n"
            # Der Bus wird IN run_async aus dem Backend importiert, also
            # dort abgreifen. Die Sitzungs-ID muss stehen, sonst haelt
            # _emit_output die Ereignisse zurueck und der Test praeft einen
            # leeren Behaelter.
            "from candyconc.services.backend import copilot_event_bus as _bus\n"
            "_bus.publish = lambda event, session_id=None: ereignisse.append(event)\n"
            "WERKZEUGE = [{'type':'function','function': {'name':'run_cqlf_query',\n"
            "    'parameters': {'type':'object'}}}]\n"
            "orch = ReActOrchestrator(WERKZEUGE, call_llm, dispatch)\n"
            "orch.project = Projekt()\n"
            "orch.session.session_id = 's1'\n"
            "asyncio.run(orch.run_async('Zeig mir den KWIC-Kontext fuer und.'))\n"
            # Das AUSGELIEFERTE out aus dem Ereignisstrom holen. Alle drei
            # Verbraucher lesen in orchestrator.py dieselbe Variable
            # (:6989 Evidenzposten, :7003 SSE-Ereignis, :7006 Lineage), der
            # Evidenzposten entsteht in diesem minimalen Turn aber nur mit
            # Analysevertrag. Statt einen leeren Behaelter zu pruefen, wird
            # er hier aus GENAU dem out gebaut, das beim Ereignis ankam.
            "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
            "ausgeliefert = [e.get('toolResult', {}).get('output')\n"
            "                for e in ereignisse if e.get('event') == 'copilot.tool_result']\n"
            "posten = ''\n"
            "if ausgeliefert and isinstance(ausgeliefert[0], dict):\n"
            "    it = make_evidence_item(item_id='e', tool='run_cqlf_query',\n"
            "        tool_call_id='c1', query={'query':'und'}, output=ausgeliefert[0],\n"
            "        analysis_family='kwic')\n"
            "    posten = json.dumps(it.to_dict(), default=str)\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'roh': ROH, 'heim': HEIM,\n"
            "  'ausgelieferter_stand': ((ausgeliefert[0] or {}).get('method') or {}).get(\n"
            "      'indexFingerprint') if ausgeliefert else None,\n"
            "  'evidenz_hat_pfad': bool(posten) and HEIM in posten,\n"
            "  'evidenzposten_gebaut': bool(posten),\n"
            "  'ereignis_hat_pfad': HEIM in json.dumps(ereignisse, default=str),\n"
            "  'lineage_hat_pfad': HEIM in json.dumps(lineage, default=str),\n"
            "  'ereignisse': len(ereignisse), 'lineage': len(lineage),\n"
            "  'werkzeugergebnisse': len(ausgeliefert),\n"
            "  'dispatch_gerufen': len(gerufen)}))\n"
        )
        r = subprocess.run(
            [sys.executable, "-c", skript], capture_output=True, text=True,
            cwd=str(_WURZEL), timeout=900,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
                 "CANDYCONC_INDEX_PATH": _BENCH or ""})
        assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, r.stderr[-700:]
        return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])

    def test_kein_verbraucher_bekommt_den_rohen_pfad(self):
        e = self._verbraucher_messen()
        # Positive Klasse: alle drei Verbraucher haben wirklich etwas
        # bekommen. Ohne sie pruefte dieser Test leere Behaelter.
        assert e["werkzeugergebnisse"] >= 1, e
        assert e["ereignisse"] >= 1, e
        assert e["lineage"] >= 1, e
        assert e["evidenzposten_gebaut"] is True, e
        assert e["evidenz_hat_pfad"] is False, e
        assert e["ereignis_hat_pfad"] is False, e
        assert e["lineage_hat_pfad"] is False, e

    def test_das_ausgelieferte_out_traegt_den_kurzstand(self):
        """Die schaerfere Form: nicht nur "kein Pfad", sondern der Hash.

        Ein leeres Feld erfuellt "kein Pfad" ebenfalls. Alle drei
        Verbraucher lesen dieselbe Variable ``out``, ihr Wert im
        Ereignisstrom gilt also fuer alle drei.
        """
        e = self._verbraucher_messen()
        stand = str(e["ausgelieferter_stand"] or "")
        assert re.fullmatch(r"[0-9a-f]{12}", stand), e
        # Und die Attrappe hat den rohen Pfad wirklich geliefert.
        assert e["heim"] in e["roh"], e


@_braucht_index
class TestJ_DieProduktivnahtDesCopilots:
    """Zwei Widerlegungen der vierten Gate-Runde.

    Die erste war eine Verschlimmerung: das Antwortschema
    ``CREATE_DOCSET_RESPONSE`` ist ueber ``_obj`` gebaut, also
    ``additionalProperties: false``, und ``mcp_server`` validiert JEDES
    Ergebnis dagegen. Die drei Kappungsfelder standen nicht darin, und
    ``create_docset`` mit ``limit`` scheiterte an der eigenen Validierung:
    "Invalid result: Additional properties are not allowed (scan_limit,
    truncated, truncation_note were unexpected)", HTTP 500. Die Reparatur
    hat die Kappung also nicht gemeldet, sondern den Aufruf zerstoert.

    Die zweite: ``mask_for_cond`` hatte DREI Zweige, nicht zwei. Menge und
    String warfen EingabeFormFehler (400), ein Ordnungsvergleich mit einer
    ZAHL auf einem Feld ohne Zahlenwerte weiter RuntimeError (500), bei
    docset_intersection sogar mit verschluckter Meldung.

    Geprueft wird ueber ``dispatcher.dispatch``, die Naht, die der
    Orchestrator benutzt, nicht ueber den direkten Funktionsaufruf: genau
    dort lag der Unterschied.
    """

    # Unterprozess, weil tests/conftest.py fuer candyconc_copilot Stubs in
    # sys.modules schiebt: ein Import hier bekaeme den Stub und wuerde
    # nicht die Produktivnaht messen.
    _SKRIPT = r"""
import sys, json, asyncio
sys.path.insert(0, {src!r})
from candyconc.services.backend import server as srv
from candyconc.candyconc_copilot import query_runtime as qr
from candyconc.candyconc_copilot.dispatcher import dispatch
qr._CORPUS_INDEX = srv.get_corpus(None)

def ruf(args):
    tc = {{"id": "1", "function": {{"name": "create_docset",
                                  "arguments": json.dumps(args)}}}}
    try:
        r = dispatch(tc, None)
        if asyncio.iscoroutine(r):
            r = asyncio.run(r)
        return {{"ok": True, "wert": r}}
    except Exception as exc:
        return {{"ok": False, "fehler": str(exc)}}

aus = {{
    "gedeckelt": ruf({{"query": 'cql:[pos="NOUN"]', "limit": 100}}),
    "ungedeckelt": ruf({{"query": 'cql:[pos="NOUN"]'}}),
    "metadaten": ruf({{"meta_filters": {{"register": "social"}}}}),
}}
for name, wert in (("menge", ["test", "train"]), ("skalar", "test"), ("zahl", 5)):
    aus["op_" + name] = ruf({{"meta_filters": {{"split": {{"op": ">=", "value": wert}}}}}})
sys.stdout.write("<<<JSON>>>" + json.dumps(aus))
"""

    @classmethod
    def _messung(cls) -> dict:
        import json
        import subprocess
        import sys

        skript = cls._SKRIPT.format(src=str(_WURZEL / "src"))
        # SAUBERE Umgebung, nicht os.environ geerbt. Frueher lief der
        # Unterprozess mit allem, was vorherige Tests gesetzt hatten
        # (Projektdatei, Sicherheitsmodus, Korpusalias), und die Klasse war
        # isoliert gruen und im Suitekontext rot. Ein Test, dessen Ergebnis
        # von seinen Nachbarn abhaengt, misst nicht den Produktivpfad.
        r = subprocess.run(
            [sys.executable, "-c", skript], capture_output=True, text=True,
            cwd=str(_WURZEL), timeout=900,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "CANDYCONC_INDEX_PATH": _BENCH,
            },
        )
        assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, (
            f"Messlauf gescheitert (rc={r.returncode}): {r.stderr[-600:]}")
        return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])

    def test_gedeckelt_meldet_die_kappung_statt_zu_scheitern(self):
        m = self._messung()
        assert m["gedeckelt"]["ok"] is True, m["gedeckelt"]
        d = m["gedeckelt"]["wert"]
        # NUR das Kennzeichen: der statische Prompt-Kern hat ein hartes
        # Limit von 31.000 Zeichen, und jedes Schemafeld muss in der
        # Werkzeugdoku stehen. Drei Namen dort ergaben 31.102. Das Modell
        # kennt sein eigenes limit. Die REST-Antwort fuehrt weiterhin
        # scan_limit und truncation_note, gepinnt in TestA.
        assert d["truncated"] is True, d
        assert "truncation_note" not in d, d
        assert d["doc_count"] < m["ungedeckelt"]["wert"]["doc_count"]

    def test_ungedeckelt_traegt_das_feld_nicht(self):
        assert "truncated" not in self._messung()["ungedeckelt"]["wert"]

    def test_der_metadaten_zweig_laeuft_weiter(self):
        d = self._messung()["metadaten"]
        assert d["ok"] is True, d
        assert d["wert"]["source"] == "metadata" and d["wert"]["doc_count"] > 0

    @pytest.mark.parametrize("gestalt", ["menge", "skalar", "zahl"])
    def test_ordnungsvergleich_ist_400_in_JEDER_wertgestalt(self, gestalt):
        """Vorher: Menge und String 400, Zahl 500."""
        e = self._messung()["op_" + gestalt]
        assert e["ok"] is False, e
        assert '"status":400' in e["fehler"], e["fehler"][:200]
        assert '"status":500' not in e["fehler"], e["fehler"][:200]
