"""Nodes and collocates apply the same case-normalization policy."""

from __future__ import annotations

import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_BENCH and os.path.isdir(_BENCH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)

KLASSE = ("und", "Und", "UND")
# Reference values measured through the tool.
O11_KLASSE = 189
F2_KLASSE = 919
NODE_FREQ = 1241


def _werkzeug():
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    return _load_real_tool_wrappers()


def _zeilen(min_freq: int, term: str = "die"):
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    ergebnis = _werkzeug().collocate_stats_tool(
        term=term, window=5, min_freq=min_freq
    )
    return ergebnis, {str(z.get("word")): z for z in (ergebnis.get("rows") or [])}


# ------------------------------------------------- was HEUTE schon gilt


def test_der_knoten_faltet_auf_dem_klartext_pfad():
    """Alle drei Schreibungen des Knotens liefern dieselbe Tafel."""
    werte = []
    for term in ("die", "Die", "DIE"):
        ergebnis, _ = _zeilen(1, term=term)
        werte.append(int(ergebnis.get("node_frequency") or 0))
    assert werte == [NODE_FREQ] * 3, f"Knoten faltet nicht mehr: {werte}"


def test_die_klasse_ist_ueber_drei_zeilen_verteilt():
    """Der Befund, als laufender Beleg. Faellt dieser Test, ist er behoben."""
    _, zeilen = _zeilen(1)
    sichtbar = {w: zeilen[w] for w in KLASSE if w in zeilen}
    assert len(sichtbar) == 3, f"nicht mehr drei Zeilen: {sorted(sichtbar)}"
    assert sum(int(z["f"]) for z in sichtbar.values()) == O11_KLASSE
    assert sum(int(z["f2"]) for z in sichtbar.values()) == F2_KLASSE


def test_die_schwelle_zerschneidet_die_klasse():
    """Warum eine Faltung VOR den min_count-Waechter gehoeren WUERDE.

    Bei min_freq=5 faellt UND (O11=2) durch die Schwelle. Wer die sichtbaren
    Zeilen aufsummiert, bekommt 187 statt 189. Ein Umsetzungsversuch, der
    erst schwellt und dann faltet, verschoebe den Fehler an die Schwelle.
    """
    _, zeilen = _zeilen(5)
    sichtbar = {w: zeilen[w] for w in KLASSE if w in zeilen}
    assert "UND" not in sichtbar, "UND ueberlebt die Schwelle wider Erwarten"
    assert sum(int(z["f"]) for z in sichtbar.values()) == 187
    assert sum(int(z["f2"]) for z in sichtbar.values()) == 910


def test_die_asymmetrie_wird_wenigstens_ausgewiesen():
    """Solange die Richtung offen ist, muss die Antwort sie NENNEN.

    Das ist unter beiden Auswegen richtig und deshalb der Teil, der jetzt
    schon gilt.
    """
    from candyconc.analysis_defaults import collocation_method_extra

    m = collocation_method_extra()
    # This class preserves the distinction between sharp s and ss.
    assert m["node_case_policy"] == "lowercase_class"
    assert m["collocate_case_policy"] == "surface_form"
    assert "mehrere Zeilen" in m["case_policy_asymmetry"]
    assert "attribute=lemma" in m["case_policy_asymmetry"]


# ------------------------------------------------------- das Ziel


@pytest.mark.xfail(
    reason=(
        "ZURUECKGESTELLT, nicht vergessen. Eine Umsetzung lag am 2026-08-31 "
        "lauffaehig vor (Faltung vor dem min_count-Waechter, f(v) ueber die "
        "Klasse in BEIDEN f2-Berechnungen, Aufschluesselung je Schreibung, "
        "Cache-Marke) und lieferte O11=189/f2=919 bei beiden Schwellen. Sie "
        "liess 13 Tests fallen, darunter die DOKUMENTIERTE Zusage von "
        "tests/backend/test_collocates_lemma_attribute_t2.py: 'attribute=word "
        "keeps the case variants separate', 'attribute=lemma merges'. Der "
        "andere Ausweg, den Knoten nicht mehr zu falten, bricht den B3-Fix, "
        "der die Klartextsuche und das Werkzeug zur Deckung bringt. Beide "
        "Auswege brechen einen bestehenden Vertrag. Die Richtung gehoert in "
        "die Runde, nicht in einen Alleingang um drei Uhr nachts."
    ),
    strict=True,
)
def test_eine_zeile_je_klasse_mit_klassenzahlen():
    """Das Ziel, falls die Runde sich fuer das Falten entscheidet."""
    _, zeilen = _zeilen(5)
    assert "Und" not in zeilen and "UND" not in zeilen, (
        "Die Klasse steht noch in mehreren Zeilen"
    )
    z = zeilen["und"]
    assert int(z["f"]) == O11_KLASSE, "Faltung nach der Schwelle zaehlt 187"
    assert int(z["f2"]) == F2_KLASSE
    assert z.get("surface_variants") == {"und": 167, "Und": 20, "UND": 2}, (
        "Die Aufschluesselung muss die ZAEHLUNG je Schreibung tragen, nicht "
        "nur die Schreibungen: sonst ist der Fall Sie gegen sie verloren."
    )


@pytest.mark.xfail(reason="Siehe oben, dieselbe Umsetzung.", strict=True)
def test_ziel_die_antwort_nennt_ihre_fallpolitik():
    ergebnis, _ = _zeilen(1)
    assert ergebnis.get("case_policy"), (
        "Die Tafel faltet, und nichts in der Antwort sagt es."
    )


@pytest.mark.xfail(
    reason=(
        "Noch nicht umgesetzt. Die CQL-Route ist per Vorgabe fallempfindlich "
        "(gemessen: cql:[word=\"Sie\"] gibt 116, Klartext gibt 354). Dort "
        "MUSS das Kollokat ungefaltet bleiben, sonst entsteht die gespiegelte "
        "Asymmetrie."
    ),
    strict=True,
)
def test_ziel_cql_bleibt_wortgetreu():
    ergebnis, zeilen = _zeilen(1, term='cql:[word="Sie"]')
    assert int(ergebnis.get("node_frequency") or 0) == 116, (
        "Die CQL-Route hat angefangen zu falten"
    )
    assert ergebnis.get("case_policy") == "wortgetreu"
