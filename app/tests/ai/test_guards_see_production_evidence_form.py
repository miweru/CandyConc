"""Guards consume the same evidence representation as the production answer path."""

from __future__ import annotations

import ast
import pathlib

import pytest

from candyconc.candyconc_copilot.evidence_access import feld, flaeche
from candyconc.candyconc_copilot.question_coverage import alle_luecken_saetze
from candyconc.candyconc_copilot.row_spelling_note import alle_saetze

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


class AlsObjekt:
    """Die Form, die die alten Tests erfunden haben."""

    def __init__(self, **felder):
        for name, wert in felder.items():
            setattr(self, name, wert)


ZEILE = {"word": "Arm", "target_freq": 2, "surface_variants": {"target": {"arm": 2}}}

#: Die Zeilen liegen UNTER "rows". Die erste Fassung dieser Tests legte sie
#: flach auf die Oberflaeche, eine Form, die es in der Produktion nicht gibt,
#: und bestaetigte damit eine Wache, die im Produkt schwieg.
FLAECHE_MIT_ZEILE = {"status": "success", "rows": [ZEILE]}


def _beide_formen(**felder):
    return [dict(felder), AlsObjekt(**felder)]


# ------------------------------------------------ die Form der Produktion


def test_orchestrator_fuehrt_dicts():
    """Wenn sich das aendert, muss dieser Test es sagen, nicht die Nutzerin.

    Die Wachen lesen ueber evidence_access und vertragen beides. Diese
    Zusicherung haelt fest, WORAUF sie sich einstellen muessen.
    """
    quelle = (SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py").read_text(
        encoding="utf-8"
    )
    baum = ast.parse(quelle)
    gefunden = []
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.AnnAssign) and isinstance(knoten.target, ast.Attribute):
            if knoten.target.attr == "_turn_evidence_items":
                gefunden.append(ast.unparse(knoten.annotation))
    assert gefunden, "_turn_evidence_items nicht mehr annotiert"
    assert all("Dict" in a or "dict" in a for a in gefunden), (
        f"Belegform geaendert: {gefunden}. Die Wachen lesen ueber belegzugriff "
        "und vertragen dict UND Objekt, aber die Tests hier bilden die "
        "Produktion ab und muessen mitgezogen werden."
    )


# ------------------------------------------------------- die Schreibungswache


@pytest.mark.parametrize("beleg", _beide_formen(fact_surface=FLAECHE_MIT_ZEILE))
def test_schreibungswache_sieht_beide_formen(beleg):
    saetze = alle_saetze("Der Arm zeigt 2 Treffer.", [beleg])
    assert saetze, f"blind fuer {type(beleg).__name__}"
    assert "„arm“" in saetze[0]


def test_schreibungswache_war_blind_fuer_dicts():
    """Der gemeldete Ausfall, als eigener Test.

    Nicht 'sie funktioniert', sondern 'sie funktioniert an DIESER Form'.
    """
    produktionsform = {
        "tool": "keyness",
        "status": "success",
        "fact_surface": FLAECHE_MIT_ZEILE,
        "query": "{}",
    }
    assert alle_saetze("Der Arm zeigt 2 Treffer.", [produktionsform])


def test_schreibungswache_faellt_auf_die_modellsicht_zurueck():
    """to_dict(include_fact_surface=False) kuerzt an einer Naht bewusst."""
    nur_modellsicht = {"tool": "keyness", "raw_surface": FLAECHE_MIT_ZEILE}
    assert alle_saetze("Der Arm zeigt 2 Treffer.", [nur_modellsicht])


# --------------------------------------------------------- die Deckungswache


@pytest.mark.parametrize(
    "beleg", _beide_formen(raw_surface={"window": 5}, query='{"window": 5}')
)
def test_deckungswache_sieht_beide_formen(beleg):
    saetze = alle_luecken_saetze("Rechne mir Fenster 1, 5 und 10 vor.", [beleg])
    assert saetze, f"blind fuer {type(beleg).__name__}"
    assert "10" in saetze[0]


def test_deckungswache_liest_die_anfrage_als_rueckfall():
    """Ohne raw_surface-Feld faellt sie auf query zurueck, in beiden Formen."""
    for beleg in _beide_formen(query='{"window": 5}'):
        assert alle_luecken_saetze("Fenster 1, 5 und 10 bitte", [beleg])


# ------------------------------------------------------------- der Zugriff


def test_zugriff_vertraegt_beide_formen():
    assert flaeche({"raw_surface": {"a": 1}}) == {"a": 1}
    assert flaeche(AlsObjekt(raw_surface={"a": 1})) == {"a": 1}
    assert flaeche({"raw_surface": None}) is None
    assert flaeche({"raw_surface": "kein Mapping"}) is None
    assert flaeche({}) is None
    assert flaeche(None) is None
    assert flaeche("Zeichenkette") is None


def test_zugriff_gibt_den_ersatz_bei_none():
    """Ein vorhandenes Feld mit Wert None ist so gut wie keines."""
    assert feld({"query": None}, "query", "") == ""
    assert feld(AlsObjekt(query=None), "query", "") == ""
    assert feld({"query": "x"}, "query", "") == "x"


# ====================================================================
# Der entscheidende Teil: die Belege werden GEBAUT wie in der Produktion,
# nicht erfunden. make_evidence_item(...).to_dict() ist woertlich das, was
# orchestrator.py:7123 in _round_evidence_items ablegt.
#
# Drei unabhaengige Stummschalter hatten die Schreibungswache abgeschaltet,
# und jeder allein genuegte:
#   (a) dict statt Objekt
#   (b) die Zeilen liegen unter ["rows"], gesucht wurde oben
#   (c) surface_variants wurde zu 120-Zeichen-Text verdichtet
# Ein Test, der nur (a) prueft, bleibt gruen, waehrend die Wache schweigt.
# ====================================================================


def _echter_posten(werkzeug: str, ausgabe: dict, anfrage: dict | None = None) -> dict:
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return make_evidence_item(
        item_id=f"E_{werkzeug}_1",
        tool=werkzeug,
        tool_call_id="tc-1",
        query=anfrage or {},
        output=ausgabe,
        analysis_family="contrast_keyness" if werkzeug == "keyness" else "collocation",
    ).to_dict()


KEYNESS_ZEILE = {
    "word": "Arm",
    "target_freq": 2,
    "reference_freq": 0,
    "ll_signed": 3.4,
    "surface_variants": {"target": {"arm": 2}},
}


def test_schreibungswache_am_echten_belegposten():
    posten = _echter_posten("keyness", {"status": "success", "rows": [KEYNESS_ZEILE]})
    assert isinstance(posten, dict), "Produktion legt dicts ab"
    saetze = alle_saetze("Die Zeile Arm zeigt 2 Treffer.", [posten])
    assert saetze, (
        "Die Wache schweigt am echten Belegposten. Genau so war sie zwei "
        "Commits lang abgeschaltet, bei gruenen Tests."
    )
    assert "„arm“" in saetze[0]


def test_die_aufschluesselung_ueberlebt_als_struktur():
    """Als 120-Zeichen-Text kann keine Wache sie auswerten."""
    posten = _echter_posten("keyness", {"status": "success", "rows": [KEYNESS_ZEILE]})
    zeile = (posten["fact_surface"]["rows"])[0]
    assert isinstance(zeile.get("surface_variants"), dict), (
        f"verdichtet zu {type(zeile.get('surface_variants')).__name__}"
    )
    assert zeile["surface_variants"] == {"target": {"arm": 2}}


def test_deckungswache_am_echten_belegposten():
    posten = _echter_posten(
        "collocate_stats",
        {"status": "success", "window": 5, "node_frequency": 10,
         "rows": [{"word": "x", "f": 3, "f2": 9, "logdice": 7.0}]},
        {"term": "Rolle", "window": 5},
    )
    saetze = alle_luecken_saetze("Rechne mir Fenster 1, 5 und 10 vor.", [posten])
    assert saetze and "10" in saetze[0]


# ---------------------------------------------------------------- Laerm


def test_kein_anhang_ohne_zitierte_zahl():
    """Faltklassen-Etiketten SIND deutsche Alltagswoerter.

    Auf dem Testindex tragen fünf der fünfzig häufigsten Klassen ihre Zahl
    nicht mehrheitlich, und es sind ausnahmslos Artikel und Pronomen. Eine
    Antwort, die keine einzige Zeile zitiert, bekam 347 Zeichen Anhang auf
    70 Zeichen Antwort.
    """
    zeilen = [
        {"word": "Die", "target_freq": 1241,
         "surface_variants": {"target": {"die": 1028, "Die": 206, "DIE": 7}}},
        {"word": "Sie", "target_freq": 354,
         "surface_variants": {"target": {"sie": 238, "Sie": 116}}},
        {"word": "Was", "target_freq": 99,
         "surface_variants": {"target": {"was": 63, "Was": 36}}},
    ]
    posten = _echter_posten("keyness", {"status": "success", "rows": zeilen})
    prosa = "Die Verteilung ist schief. Was auffällt: Sie steht oft am Satzanfang."
    assert alle_saetze(prosa, [posten]) == []


def test_anhang_sobald_die_zahl_dasteht():
    zeile = {"word": "Die", "target_freq": 1241,
             "surface_variants": {"target": {"die": 1028, "Die": 206, "DIE": 7}}}
    posten = _echter_posten("keyness", {"status": "success", "rows": [zeile]})
    for antwort in ("Die kommt 1241 mal vor.", "Die steht 1.241 mal im Korpus."):
        saetze = alle_saetze(antwort, [posten])
        assert saetze, f"kein Anhang für {antwort!r}"
        assert "„die“" in saetze[0]


def test_fremde_zahl_loest_nicht_aus():
    zeile = {"word": "Die", "target_freq": 1241,
             "surface_variants": {"target": {"die": 1028, "Die": 206, "DIE": 7}}}
    posten = _echter_posten("keyness", {"status": "success", "rows": [zeile]})
    assert alle_saetze("Die Liste hat 42 Einträge.", [posten]) == []
