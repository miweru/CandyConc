"""P2.3: der Methodensteckbrief war an drei Stellen leer.

Gemessen am Testindex ueber die dreizehn Messwerkzeuge, jedes mit einem
ECHTEN Aufruf und einem ueber ``make_evidence_item`` gebauten Posten, also
auf dem Produktivpfad. ``similar_words`` ist am Testindex nicht
auswertbar (kein Wort-Thesaurus, ``status: unavailable``), es bleiben
zwoelf.

Vorher
------
    Index-Fingerabdruck    0 von 12
    word_sketch            kein Steckbrief (null bits -> continue)
    trend_analysis         nur "Suche: und"
    ngram_frequency        kein n

Drei Ursachen, alle in der Zuleitung, nicht in den Werkzeugen:

1. ``extract_raw_surface`` fuehrt eine Namensliste, und der
   ``method``-Block darf daraus nur SECHS Unterschluessel behalten
   (attribute, window, within_sentence, sort_by, min_freq, floor_mode).
   ``trend_analysis`` hat KEINEN davon. Sein Block, der als einziger den
   Indexstand traegt, fiel deshalb ganz heraus. Genau dieses Werkzeug
   nennt der Plan als Muster fuer die uebrigen.
2. ``min_n``/``max_n`` standen nicht auf der Liste, ``word_sketch``
   lieferte nur ``min_freq``, und der Renderer las es im generischen
   Zweig nicht. Ohne bits greift ``if not bits: continue``, und das
   Werkzeug verschwindet aus dem Steckbrief.
3. Den Indexstand liefert genau ein Werkzeug, und er beschreibt ohnehin
   den KORPUS, nicht den Aufruf. Zwoelf gleiche Fingerabdruecke unter
   einer Antwort waeren Rauschen, deshalb steht er EINMAL.

Zwei Defekte der ersten Reparatur, hier mitgepinnt
--------------------------------------------------
``_index_fingerprint`` liefert ``<absoluter Pfad>@<mtime_ns>``. Die erste
Fassung nahm davon sechzehn Zeichen, und in der Antwort stand "Indexstand
/Users/name/P": ein abgeschnittenes Heimatverzeichnis, das nichts
identifiziert und den Pfad des Betreibers preisgibt. Und die Erweiterung
der Namensliste allein genuegte nicht, weil der Renderer die neuen Namen
nicht las.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)

# Werkzeug -> Aufrufargumente. Echte Aufrufe, keine Attrappen.
_AUFRUFE = {
    "query_count": dict(query="und"),
    "run_cqlf_query": dict(query='[word="und"]'),
    # ``top_n`` steht NICHT in der Signatur des Produktivpfades. Ein
    # Argument, das der geprueste Code nicht kennt, macht aus dem Test
    # einen Test einer anderen Sache.
    "frequency_list": dict(limit=5),
    "collocate_stats": dict(term="und", window=5),
    "dispersion_offsets": dict(term="und"),
    "lexical_diversity": dict(),
    "ngram_frequency": dict(min_n=2, max_n=3, limit=3),
    "trend_analysis": dict(date_field="split", query="und"),
    "word_sketch": dict(term="und"),
    "document_search": dict(term="und", top_n=2),
    "metadata_values": dict(fields=["split"]),
    "keyness": dict(target=["a", "a"], reference=["b"]),
}

_BASIS = "Kernbefund: 12 Treffer."


# tests/conftest.py schiebt fuer ``candyconc.candyconc_copilot`` Stubs in
# sys.modules. Ein Import hier bekaeme sie, und dieser Test wuerde dann den
# Stub messen statt den Produktivpfad. Deshalb laeuft die Messung in einem
# SAUBEREN Unterprozess: echte Werkzeuge, echter Index, echte Politur.
_MESSSKRIPT = r"""
import json, sys
sys.path.insert(0, {src!r})
from candyconc.services.backend import server as srv
from candyconc.candyconc_copilot import query_runtime as qr
from candyconc.candyconc_copilot import recipe_runtime as rr
from candyconc.candyconc_copilot import tool_wrappers as tw
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

assert "tests" not in str(getattr(tw, "__file__", "")), "Stub statt Produktivmodul"
qr._CORPUS_INDEX = srv.get_corpus(None)
AUFRUFE = json.loads(sys.argv[1])
BASIS = sys.argv[2]
aus = {{}}
for name, kwargs in AUFRUFE.items():
    fn = getattr(tw, name + "_tool", None)
    if fn is None:
        continue
    try:
        out = fn(**kwargs)
    except Exception:
        continue
    if not isinstance(out, dict) or out.get("status") != "success":
        continue
    posten = [make_evidence_item(
        item_id="ev1", tool=name, tool_call_id="c1",
        query=kwargs, output=out, analysis_family="x",
    )]
    aus[name] = rr.methodensteckbrief_anhaengen(BASIS, posten)
sys.stdout.write("<<<JSON>>>" + json.dumps(aus))
"""


@pytest.fixture(scope="module")
def steckbriefe():
    """Ein echter Aufruf je Werkzeug, ein Steckbrief je Aufruf."""
    import json
    import subprocess
    import sys

    wurzel = Path(__file__).resolve().parents[2]
    skript = _MESSSKRIPT.format(src=str(wurzel / "src"))
    lauf = subprocess.run(
        [sys.executable, "-c", skript, json.dumps(_AUFRUFE), _BASIS],
        capture_output=True, text=True, cwd=str(wurzel), timeout=900,
        env={**os.environ, "CANDYCONC_INDEX_PATH": _BENCH},
    )
    # KEIN skip. Stuerzt der geprueste Code ab, ist genau das der Befund.
    # Ein Skip haette den Test entwaffnet: er waere gruen geblieben,
    # waehrend die Politur beim ersten Aufruf gebrochen waere.
    assert lauf.returncode == 0 and "<<<JSON>>>" in lauf.stdout, (
        f"Messlauf gescheitert (rc={lauf.returncode}): {lauf.stderr[-600:]}"
    )
    aus = json.loads(lauf.stdout.split("<<<JSON>>>", 1)[1])
    # Require every tool listed in _AUFRUFE. Skipping a failed tool would
    # hide the missing provenance this test is intended to detect.
    fehlt = sorted(set(_AUFRUFE) - set(aus))
    assert not fehlt, (
        f"{len(fehlt)} Messwerkzeug(e) nicht auswertbar: {fehlt}. Dieser "
        "Test bewacht den Steckbrief JEDES Werkzeugs, ein stiller Ausfall "
        "wuerde ihn gruen lassen, ohne dass er etwas geprueft haette."
    )
    return aus


def test_jedes_auswertbare_werkzeug_bekommt_einen_steckbrief(steckbriefe):
    """word_sketch hatte null bits und fiel ganz heraus."""
    ohne = [n for n, t in steckbriefe.items() if t.strip() == _BASIS]
    assert ohne == [], f"ohne Steckbrief: {ohne}"


def test_der_indexstand_steht_auf_jedem(steckbriefe):
    """Vorher auf keinem einzigen."""
    ohne = [n for n, t in steckbriefe.items() if "Indexstand" not in t]
    assert ohne == [], f"ohne Indexstand: {ohne}"


def test_der_indexstand_steht_genau_EINMAL(steckbriefe):
    """Er beschreibt den Korpus, nicht den Aufruf."""
    for name, text in steckbriefe.items():
        assert text.count("Indexstand") == 1, name


def test_der_indexstand_ist_ein_hash_und_kein_pfad(steckbriefe):
    """Die erste Fassung druckte "Indexstand /Users/name/P"."""
    heim = os.path.expanduser("~")
    for name, text in steckbriefe.items():
        assert heim not in text, f"{name}: Heimatverzeichnis im Antworttext"
        assert "/" not in text.split("Indexstand", 1)[1].split("\n", 1)[0], name
        wert = re.search(r"Indexstand ([0-9a-f]+)", text)
        assert wert is not None, f"{name}: kein Hexwert hinter Indexstand"
        assert len(wert.group(1)) == 12, name


def test_alle_werkzeuge_nennen_denselben_indexstand(steckbriefe):
    """Ein Korpus, ein Stand. Sonst waere die Angabe wertlos."""
    werte = {re.search(r"Indexstand ([0-9a-f]+)", t).group(1)
             for t in steckbriefe.values()}
    assert len(werte) == 1, werte


def test_trend_analysis_nennt_seine_inferentielle_provenienz(steckbriefe):
    """Vorher stand dort nur "Suche: und".

    Der ganze method-Block fiel aus extract_raw_surface heraus, weil
    keiner der sechs erlaubten Unterschluessel in trend_analysis vorkommt.
    """
    text = steckbriefe.get("trend_analysis")
    if text is None:
        pytest.skip("trend_analysis nicht auswertbar")
    for angabe in ("Zeitfeld", "Granularität", "Konfidenzverfahren",
                   "Konfidenzniveau"):
        assert angabe in text, f"{angabe} fehlt: {text[:200]}"


def test_ngram_nennt_sein_n(steckbriefe):
    """Eine n-Gramm-Zahl ohne n ist nicht einzuordnen."""
    text = steckbriefe.get("ngram_frequency")
    if text is None:
        pytest.skip("ngram_frequency nicht auswertbar")
    assert "n von 2 bis 3" in text, text[:200]


def test_word_sketch_nennt_seine_schwelle(steckbriefe):
    """Eine Schwelle, die Zeilen aus einer Tabelle nimmt, gehoert daneben."""
    text = steckbriefe.get("word_sketch")
    if text is None:
        pytest.skip("word_sketch nicht auswertbar")
    assert "Mindestfrequenz" in text, text[:200]


def test_die_faltung_steht_wo_das_werkzeug_sie_meldet(steckbriefe):
    """query_count und run_cqlf_query liefern case_insensitive."""
    for name in ("query_count", "run_cqlf_query"):
        text = steckbriefe.get(name)
        if text is None:
            continue
        assert "Groß-/Kleinschreibung" in text, f"{name}: {text[:200]}"


def test_ohne_evidenz_entsteht_KEIN_leerer_steckbrief():
    """Eine Ueberschrift ohne Angaben waere ein leeres Versprechen."""
    import json
    import subprocess
    import sys

    wurzel = Path(__file__).resolve().parents[2]
    skript = (
        "import sys, json; sys.path.insert(0, %r)\n"
        "from candyconc.candyconc_copilot import recipe_runtime as rr\n"
        "b = 'Kernbefund: 12 Treffer.'\n"
        "leer = rr.methodensteckbrief_anhaengen(b, []) == b\n"
        "ohne = rr._indexstand_zeile([])\n"
        "kurz = rr._indexstand_kurz('')\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps(\n"
        "    {'leer': leer, 'ohne_ist_kurz': isinstance(ohne, str),\n"
        "     'leere_signatur': kurz}))\n"
    ) % (str(wurzel / "src"),)
    lauf = subprocess.run(
        [sys.executable, "-c", skript], capture_output=True, text=True,
        cwd=str(wurzel), timeout=300,
        env={**os.environ, "CANDYCONC_INDEX_PATH": _BENCH or ""},
    )
    # A failed measurement must fail the test rather than become a skip.
    assert lauf.returncode == 0 and "<<<JSON>>>" in lauf.stdout, (
        f"Messlauf gescheitert (rc={lauf.returncode}): {lauf.stderr[-600:]}")
    ergebnis = json.loads(lauf.stdout.split("<<<JSON>>>", 1)[1])
    assert ergebnis["leer"] is True
    # Eine leere Signatur ergibt KEINE Zeile, nicht "Indexstand ".
    assert ergebnis["leere_signatur"] == ""
