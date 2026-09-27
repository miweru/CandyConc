"""Vier bestaetigte Befunde des Klassen-Gates ueber fd98139616.

Das Gate hat nicht nach Aenderungen gesucht, sondern nach FEHLERKLASSEN,
und jede Klasse ein weiteres Mal getroffen.

A. Kontrollrahmen: Modelltext an der Zitatwache vorbei, fuenftes Mal
   PLAN, CLARIFY und ACTION tragen Modelltext (goal, steps,
   expectedOutcome, question, options, rationale, summary, reason). Der
   Orchestrator gab sie als copilot.plan / copilot.clarify /
   copilot.action ROH an die Oberflaeche. Die Reparatur der pausierenden
   Landungen deckte nur den RUECKGABEWERT: derselbe erfundene Satz wurde
   im Antworttext zu "[Beleg fehlt]" und stand im Ereignis daneben
   woertlich. Zwei Ausgaenge desselben Turns, zwei Wahrheiten.

B. Die MCP-Waesche war nie im Baum
   Commit eb090e075b behauptet, POST /mcp/call rufe denselben Helfer. Der
   Aufruf stand nicht in mcp_server.py. Eine Behauptung ueber den
   Baumzustand ohne Verifikation, genau die Sorte, die dieser Auftrag
   verbietet.

C. create_docset verwarf eines von zwei Filterdikten
   Die Auswahl war ``meta_filters if (meta_filters and query_text) else
   (filters or meta_filters or {})``, also immer genau EINES. Gemessen
   ueber dispatcher.dispatch am Testindex:
       {"filters":{"split":"train"},"meta_filters":{"split":"test"}}
           -> 1317 Dokumente, status success   (richtig waeren 0)
       {"query":"und","filters":{"split":"test"},
        "meta_filters":{"model":"human"}} -> 741   (richtig waeren 247)
   In EINEM Dikt uebergeben liefert dieselbe Kombination das richtige
   Ergebnis, die Vereinigung war also moeglich und nur nicht gemacht.

D. Der Zaehl-Cache teilte seinen Schluessel mit dem ungefilterten Aufruf
   ``_query_count_key`` strippt date und genre, die Maske prueft die ROHE
   Wahrheit, und ein Leerraum-String ist truthy. Am Testindex, term=und:
       ungefiltert zuerst, dann genre="   " -> 919, byte-gleich
       genre="   " zuerst, dann ungefiltert -> 0 von 919
   Der zweite Fall vergiftet den prozessweiten Cache, und /query/stream
   lieferte 50 KWIC-Zeilen zusammen mit count 0. test_meta_filters_golden
   .test_anchor5 pinnt denselben Vertrag fuer den Dikt-Eingang:
   Leerraum heisst "dieses Feld ist nicht gefiltert".
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_WURZEL = Path(__file__).resolve().parents[2]

_braucht_index = pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)

_FABRIKAT = ("der jungen Maenner sind keine Fluechtlinge. "
             "Sie sind ruecksichtslose Invasoren.")


def _im_unterprozess(skript: str) -> dict:
    """Sauberer Prozess: tests/conftest.py stubbt candyconc_copilot."""
    import json
    import subprocess
    import sys

    voll = f"import sys, json\nsys.path.insert(0, {str(_WURZEL / 'src')!r})\n" + skript
    r = subprocess.run(
        [sys.executable, "-c", voll], capture_output=True, text=True,
        cwd=str(_WURZEL), timeout=900,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "CANDYCONC_INDEX_PATH": _BENCH or ""},
    )
    assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, (
        f"Messlauf gescheitert (rc={r.returncode}): {r.stderr[-600:]}")
    return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])


class TestA_KontrollrahmenLaufenDurchDieWache:
    def test_ein_erfundenes_zitat_ueberlebt_den_rahmen_nicht(self):
        from candyconc.candyconc_copilot import recipe_runtime as rr

        # `tool` produktivtreu: orchestrator.py:6997 legt
        # `evidence_item.to_dict()` ab, und das Feld ist immer gesetzt. Die
        # Wache entscheidet nach HERKUNFT, weil die Form einer Zeile allein
        # nicht reicht (semantic_cluster_words spiegelt Modelltext).
        evidenz = [{"tool": "document_search",
                    "grounding_surface": ["Die Abgeordnete sprach ueber Flucht."]}]
        rahmen = {
            "question": f'Meinten Sie die Passage "{_FABRIKAT}"?',
            "options": [f'"{_FABRIKAT}"', "etwas anderes"],
            "rationale": f'Im Korpus steht "{_FABRIKAT}".',
            "timeout": 60,
            "blocking": True,
        }
        sauber = rr.kontrollrahmen_bewacht(rahmen, evidenz)
        flach = repr(sauber)
        assert "Invasoren" not in flach, sauber
        # Und die nicht-textlichen Felder bleiben unangetastet.
        assert sauber["timeout"] == 60 and sauber["blocking"] is True

    def test_ein_belegtes_zitat_bleibt(self):
        """Eine Wache, die alles streicht, besteht jeden Fabrikationstest."""
        from candyconc.candyconc_copilot import recipe_runtime as rr

        satz = "Die Abgeordnete sprach ueber Flucht."
        sauber = rr.kontrollrahmen_bewacht(
            {"question": f'Meinten Sie "{satz}"?'},
            [{"tool": "document_search", "grounding_surface": [satz]}],
        )
        assert satz in sauber["question"], sauber

    def test_der_orchestrator_bewacht_ALLE_rahmen_an_einer_stelle(self):
        quelle = (_WURZEL / "src" / "candyconc" / "candyconc_copilot"
                  / "orchestrator.py").read_text(encoding="utf-8")
        i = quelle.index("def _process_llm_response(")
        rumpf = quelle[i: quelle.index("\n    def ", i + 10)]
        assert "kontrollrahmen_bewacht" in rumpf, rumpf[-400:]
        # Kein roher extract_all_control_frames irgendwo sonst im Modul.
        assert quelle.count("extract_all_control_frames(") == 1


class TestB_DieMcpWaescheIstImBaum:
    def test_execute_tool_call_ruft_den_helfer(self):
        quelle = (_WURZEL / "src" / "candyconc" / "services"
                  / "mcp_server.py").read_text(encoding="utf-8")
        i = quelle.index("async def execute_tool_call(")
        rumpf = quelle[i:]
        assert "werkzeugausgabe_ohne_betreiberpfad" in rumpf, (
            "die Behauptung, der Helfer sitze hier, war schon einmal falsch")

    @_braucht_index
    def test_kein_betreiberpfad_in_der_mcp_antwort(self):
        e = _im_unterprozess(
            "import os, asyncio\n"
            "from candyconc.services.backend import server as srv\n"
            "from candyconc.candyconc_copilot import query_runtime as qr\n"
            "from candyconc.services.mcp_server import execute_tool_call\n"
            "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
            "heim = os.path.expanduser('~')\n"
            "r = asyncio.run(execute_tool_call(\n"
            "    {'name': 'trend_analysis',\n"
            "     'arguments': {'date_field': 'split', 'query': 'und'}}, None))\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'hat_pfad': heim in json.dumps(r),\n"
            "  'stand': (r.get('method') or {}).get('indexFingerprint', '')}))\n"
        )
        assert e["hat_pfad"] is False, e
        assert len(str(e["stand"])) == 12, e


@_braucht_index
class TestC_CreateDocsetVereinigtBeideFilter:
    @staticmethod
    def _lauf() -> dict:
        return _im_unterprozess(
            "import asyncio\n"
            "from candyconc.services.backend import server as srv\n"
            "from candyconc.candyconc_copilot import query_runtime as qr\n"
            "from candyconc.candyconc_copilot.dispatcher import dispatch\n"
            "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
            "def ruf(a):\n"
            "    tc = {'id':'1','function':{'name':'create_docset',\n"
            "          'arguments': json.dumps(a)}}\n"
            "    try:\n"
            "        r = dispatch(tc, None)\n"
            "        if asyncio.iscoroutine(r): r = asyncio.run(r)\n"
            "        return {'ok': True, 'wert': r}\n"
            "    except Exception as e:\n"
            "        return {'ok': False, 'fehler': str(e)}\n"
            "aus = {\n"
            "  'nur_split_test': ruf({'meta_filters':{'split':'test'}}),\n"
            "  'beide_disjunkt': ruf({'filters':{'split':'train'},\n"
            "                         'meta_filters':{'split':'test'}}),\n"
            "  'ein_dikt_beide': ruf({'filters':{'split':'test','model':'human'}}),\n"
            "  'getrennt_beide': ruf({'filters':{'model':'human'},\n"
            "                         'meta_filters':{'split':'test'}}),\n"
            "}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(aus))\n"
        )

    def test_widerspruechliche_filter_sind_ein_eingabefehler(self):
        """Vorher 1317 Dokumente mit status success.

        Kein Dokument kann split=train UND split=test tragen. Eine
        Zwischenfassung liess meta_filters gewinnen und meldete das
        Verworfene in einem Zusatzfeld: dieselbe Klasse noch einmal, ein
        Filter wirkt nicht und der Aufruf meldet Erfolg. 683 Dokumente
        sehen aus wie ein Befund.
        """
        m = self._lauf()
        e = m["beide_disjunkt"]
        assert e["ok"] is False, e
        assert "widerspr" in e["fehler"], e["fehler"][:200]
        assert '"status":400' in e["fehler"] or "ToolInputError" in e["fehler"], \
            e["fehler"][:200]

    def test_getrennt_uebergeben_wirkt_wie_in_einem_dikt(self):
        """Die Vereinigung war moeglich und nur nicht gemacht."""
        m = self._lauf()
        assert m["getrennt_beide"]["wert"]["doc_count"] == \
            m["ein_dikt_beide"]["wert"]["doc_count"]

    def test_ein_einzelner_filter_bleibt_unveraendert(self):
        m = self._lauf()
        d = m["nur_split_test"]["wert"]
        assert d["doc_count"] == 683, d
        assert d["doc_count"] > 0


@_braucht_index
class TestD_ZaehlschluesselUndMaskeStimmenUeberein:
    @pytest.mark.parametrize("genre", [None, "", "   ", "\t"])
    def test_leerraum_heisst_KEIN_filter_auf_beiden_seiten(self, genre):
        from candyconc.services.backend import server as srv
        from candyconc.services.backend.query_count import _query_count_key

        ohne = _query_count_key("und", "default", None, None, None)
        assert _query_count_key("und", "default", None, genre, None) == ohne
        assert srv._metadata_filter_docset_mask(
            srv.get_corpus(None), date=None, genre=genre) is None

    def test_ein_echtes_genre_wirkt_auf_beiden_seiten(self):
        """Die Gegenprobe: sonst waere der Filter schlicht abgeschafft."""
        from candyconc.services.backend import server as srv
        from candyconc.services.backend.query_count import _query_count_key

        ohne = _query_count_key("und", "default", None, None, None)
        assert _query_count_key("und", "default", None, "social", None) != ohne
        assert srv._metadata_filter_docset_mask(
            srv.get_corpus(None), date=None, genre="social") is not None

    def test_randleerraum_am_echten_wert_wird_gestrippt(self):
        """"  social  " muss dasselbe treffen wie "social"."""
        from candyconc.services.backend import server as srv

        idx = srv.get_corpus(None)
        a = srv._metadata_filter_docset_mask(idx, date=None, genre="social")
        b = srv._metadata_filter_docset_mask(idx, date=None, genre="  social  ")
        assert a is not None and b is not None
        assert int(a.sum()) == int(b.sum())
