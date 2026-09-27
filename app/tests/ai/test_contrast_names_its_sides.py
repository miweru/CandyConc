"""Ein Kontrast ohne Richtung und ohne Nenner ist nicht zitierfaehig.

Zwei Befunde der ersten Professorinnen-Runde (2026-08-29), beide an
derselben Naht.

P1 (kollokation-3, toedlich):

    "Die Richtung des Kontrasts ist aus der Antwort nicht rekonstruierbar.
     Der Text spricht von 'Seite A' und 'Seite B' und bindet beide nirgends
     an Metadaten."

Der Text ist DETERMINISTISCH erzeugt, nicht vom Modell geschrieben.

P4 (kontrast-3, toedlich):

    "Der Kontrast nennt keine Richtung und keinen Nenner, obwohl beide
     berechnet werden."

Selbst nachgezaehlt: die Nutzlast trug genau fuenf Schluessel (status,
rows, total, truncated, diagnostics). Die Kontextmassen beider Seiten
werden in ``compare_by_docset_masks`` als u_h und u_a berechnet und
verfielen danach. Ohne sie sind freq_target=122 gegen freq_reference=0
zwei Zahlen ohne Bezug.
"""

from __future__ import annotations

import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


@pytest.fixture(scope="module")
def kontrast():
    """Baut den Kontrast und RAEUMT DEN GLOBALEN ZUSTAND WIEDER AB.

    Eine Vorfassung setzte ``qr._CORPUS_INDEX`` und liess ihn stehen. Im
    Einzellauf war das unsichtbar, im Gesamtlauf fielen danach fuenf
    Orchestrator-Tests, weil sie einen anderen Werkzeugraum sahen. Ein Test,
    der die Umgebung spaeterer Tests veraendert, misst nicht nur sich
    selbst, und der Schaden faellt woanders an.
    """

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    vorher = getattr(qr, "_CORPUS_INDEX", None)
    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    # NICHT "import tool_wrappers": tests/conftest.py legt dafuer eine
    # Attrappe in sys.modules, und ein Test, der sie trifft, prueft nichts.
    from tests.ai.test_tool_wrappers_parity_r5 import (
        _load_real_tool_wrappers,
    )

    tw = _load_real_tool_wrappers()

    ziel = tw.create_docset_tool(filters={"split": "test"}, label="Testteil")
    referenz = tw.create_docset_tool(filters={"split": "train"})
    ergebnis = tw.contrast_collocates_tool(
        term="die",
        target_docset_id=ziel["docset_id"],
        reference_docset_id=referenz["docset_id"],
        window=5,
        top_n=30,
    )
    try:
        yield ziel, referenz, ergebnis
    finally:
        qr._CORPUS_INDEX = vorher


# --------------------------------------------------------------------------- #
# P4: Richtung und Nenner in der Nutzlast
# --------------------------------------------------------------------------- #

def test_die_nutzlast_nennt_beide_seiten(kontrast):
    ziel, referenz, ergebnis = kontrast
    assert ergebnis["target_docset_id"] == ziel["docset_id"]
    assert ergebnis["reference_docset_id"] == referenz["docset_id"]


def test_die_nenner_stehen_in_den_diagnosen(kontrast):
    _z, _r, ergebnis = kontrast
    d = ergebnis["diagnostics"]
    for feld in (
        "node_frequency_target", "node_frequency_reference",
        "context_mass_target", "context_mass_reference",
    ):
        assert d.get(feld) is not None, (feld, d)
        assert int(d[feld]) > 0, (feld, d[feld])
    # Die Kontextmasse MUSS groesser sein als die Ankerzahl, sonst ist eine
    # der beiden Zahlen nicht das, was ihr Name sagt.
    assert d["context_mass_target"] > d["node_frequency_target"]
    assert d["context_mass_reference"] > d["node_frequency_reference"]


def test_die_dokumentzahlen_sind_NICHT_die_nenner(kontrast):
    """Der Kern des Befundes: freq_* gegen die Dokumentzahl zu lesen waere
    eine andere, falsche Rate. Beide Groessen stehen jetzt nebeneinander
    und sind unterscheidbar."""
    _z, _r, ergebnis = kontrast
    d = ergebnis["diagnostics"]
    assert d["target_docs"] != d["context_mass_target"]
    assert d["reference_docs"] != d["context_mass_reference"]


# --------------------------------------------------------------------------- #
# P1: der Verfasser nennt die Seiten beim Namen
# --------------------------------------------------------------------------- #

def _kontrasttext(ziel, referenz, ergebnis):
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
    from candyconc.candyconc_copilot.grounding_markdown import (
        _build_contrast_markdown,
    )

    posten = [
        make_evidence_item(
            item_id="d1", tool="create_docset", tool_call_id="c1",
            query={}, output=ziel, analysis_family="contrast"),
        make_evidence_item(
            item_id="d2", tool="create_docset", tool_call_id="c2",
            query={}, output=referenz, analysis_family="contrast"),
        make_evidence_item(
            item_id="k1", tool="contrast_collocates", tool_call_id="c3",
            query={"term": "die"}, output=ergebnis,
            analysis_family="contrast"),
    ]
    return _build_contrast_markdown(posten, evidence_gaps=[])


def test_seite_a_und_seite_b_kommen_nicht_mehr_vor(kontrast):
    text = _kontrasttext(*kontrast)
    assert "Seite A" not in text, text[:400]
    assert "Seite B" not in text, text[:400]


def test_das_etikett_des_docsets_steht_im_text(kontrast):
    text = _kontrasttext(*kontrast)
    assert "Testteil" in text, text[:400]


def test_ohne_zuordnung_wird_es_gesagt_statt_geraten():
    """POSITIVE GEGENKLASSE, und die wichtigere Haelfte.

    Faellt die Zuordnung aus, darf der Verfasser nicht auf ein generisches
    "Seite A" zurueckfallen, das nach einer Bezeichnung aussieht. Er sagt,
    dass die Zuordnung nicht vorliegt.
    """
    from candyconc.candyconc_copilot.grounding_contrast import (
        kontrastseiten_benennen,
    )

    ziel, referenz = kontrastseiten_benennen([], lambda x: str(x or ""))
    assert "nicht zuzuordnen" in ziel
    assert "nicht zuzuordnen" in referenz
    assert "Seite A" not in ziel and "Seite B" not in referenz


def test_ohne_etikett_bleibt_die_kennung_eindeutig():
    """Eine Docset-Kennung ist eindeutig und nie irrefuehrend. "Seite A"
    ist beides nicht."""
    from candyconc.candyconc_copilot.grounding_contrast import (
        kontrastseiten_benennen,
    )

    class _Posten:
        def __init__(self, tool, roh):
            self.tool = tool
            self.raw_surface = roh

    posten = [
        _Posten("create_docset", {"docset_id": "abcdef1234567890"}),
        _Posten("contrast_collocates", {
            "target_docset_id": "abcdef1234567890",
            "reference_docset_id": "999",
        }),
    ]
    ziel, referenz = kontrastseiten_benennen(posten, lambda x: str(x or ""))
    assert "abcdef12" in ziel, ziel
    assert "999" in referenz, referenz


def test_die_nenner_stehen_auch_im_bericht_nicht_nur_in_der_nutzlast(kontrast):
    """Der zweite, beim ersten Anlauf uebersehene Teil des Befundes.

    Ein adversarialer Pruefer am 2026-08-29: die vier Groessen kamen zwar
    in der Nutzlast an, ein grep nach context_mass in grounding_markdown
    und grounding_contrast lieferte aber null Treffer. Die Haelfte eines
    Befundes einzuloesen und ihn als erledigt zu melden, ist die
    haeufigste Fehlerklasse dieses Projekts.
    """
    text = _kontrasttext(*kontrast)
    assert "Bezugsgrössen" in text, text[:400]
    _z, _r, ergebnis = kontrast
    d = ergebnis["diagnostics"]
    # Check the actual fixture values rather than the presence of arbitrary numbers.
    for feld in ("node_frequency_target", "context_mass_target",
                 "node_frequency_reference", "context_mass_reference"):
        assert str(d[feld]) in text, (feld, d[feld], text[:400])


def test_ohne_nenner_wird_kein_satz_behauptet():
    """POSITIVE GEGENKLASSE. Ein Satz ueber Nenner, die nicht vorliegen,
    waere wieder eine Behauptung."""
    from candyconc.candyconc_copilot.grounding_contrast import (
        kontrastnenner_satz,
    )

    class _Posten:
        def __init__(self, roh):
            self.tool = "contrast_collocates"
            self.raw_surface = roh

    assert kontrastnenner_satz([]) == ""
    assert kontrastnenner_satz([_Posten({"diagnostics": {}})]) == ""
    assert kontrastnenner_satz([_Posten({"diagnostics": {
        "node_frequency_target": 0, "context_mass_target": 10,
        "node_frequency_reference": 5, "context_mass_reference": 20}})]) == ""
