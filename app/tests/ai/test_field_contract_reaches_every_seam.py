# -*- coding: utf-8 -*-
"""Der Feldvertrag bestimmt, was das Modell von einer Zeile sieht.

``_surface_row_dict`` fuehrte EINE Vorzugsliste fuer ALLE Werkzeuge und
schnitt bei acht Schluesseln ab. Am Testindex gemessen, was davon uebrig
blieb::

    keyness, sort_by=ll_signed
      sah     word ll_signed direction target_freq reference_freq
              diff_per_million q_value low_reliability
      nicht   log_ratio  lrc  target_per_million  reference_per_million

    collocate_stats, sort_by=logdice
      sah     rank word logdice f mi3 mi t ll
      nicht   lrc  log_ratio  logdice_window

Damit waren zwei Methoden-Invarianten des statischen Prompts konstruktiv
unerfuellbar: "Rohwert und per_million zitieren, nie selbst rechnen" (keine
der beiden Raten war je sichtbar) und "Effektstaerke fuehrt" (sichtbar waren
vier Masse derselben Familie, keine Effektstaerke). Und
``claim_rules/keyness.py`` prueft Belege gegen ein Muster, das ``log_ratio=``
erwartet, ein Mass, das das Modell nie zu sehen bekam.

Ein groesseres Fenster half NICHT: bei ``limit_keys=12`` kamen ``ll``,
``chi2_cell``, ``bic`` und ``chi2`` dazu, also noch mehr Signifikanz. Die
fehlenden Felder standen in der Vorzugsliste gar nicht.

Dazu ein zweiter Befund, ohne den der Kollokationsvertrag leer liefe: die
Zeile fuehrte ``f2`` nicht. Die Engine rechnet f(v) fuer Rychlys Nenner und
warf es weg, zwei keep-Listen (Copilot und REST) liessen es nicht durch.
Ohne f(v) ist ``logdice = 14 + log2(2*O11/(f(u)+f(v)))`` nicht nachrechenbar,
denn f(u) steht als ``node_frequency`` im Kopf und f(v) stand nirgends.
"""

from __future__ import annotations

import ast
import math
import os
from pathlib import Path

import pytest

from candyconc.candyconc_copilot.grounding_field_contract import FELDVERTRAEGE

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_QUELLE = Path(__file__).resolve().parents[2] / "src" / "candyconc" / "candyconc_copilot"
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
needs_bench = pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


def _aufrufe(funktionsname: str) -> list[tuple[str, int, set[str]]]:
    """Jeder Aufruf von ``funktionsname`` im Produktivcode, mit Argumentnamen."""
    treffer: list[tuple[str, int, set[str]]] = []
    for datei in sorted(_QUELLE.glob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if not isinstance(knoten, ast.Call):
                continue
            ziel = knoten.func
            name = (
                ziel.id if isinstance(ziel, ast.Name)
                else ziel.attr if isinstance(ziel, ast.Attribute)
                else None
            )
            if name != funktionsname:
                continue
            treffer.append(
                (datei.name, knoten.lineno, {k.arg for k in knoten.keywords if k.arg})
            )
    return treffer


@pytest.mark.parametrize(
    "funktion",
    ["extract_raw_surface", "_tool_output_for_model"],
)
def test_jede_naht_reicht_den_werkzeugnamen_durch(funktion):
    """Eine Naht ohne Namen liefert still die alte Liste.

    Genau diese Klasse hat in dieser Codebasis mehrfach zugeschlagen: ein
    Vorgabewert an EINER Stelle gedreht, waehrend n Aufrufstellen den alten
    Wert hartkodierten. Deshalb wird hier gezaehlt, nicht benannt.
    """
    aufrufe = _aufrufe(funktion)
    assert aufrufe, f"{funktion} wird nirgends aufgerufen, der Test waere vakuum."
    ohne = [
        (datei, zeile)
        for datei, zeile, argumente in aufrufe
        if "werkzeug" not in argumente
    ]
    assert not ohne, (
        f"{funktion} ohne werkzeug: {ohne}. Diese Naht liefert dem Modell "
        "still die gemeinsame Vorzugsliste statt des Feldvertrags."
    )


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_keyness_zeigt_beide_raten_und_eine_effektstaerke():
    from candyconc.candyconc_copilot.grounding_evidence import extract_raw_surface

    ziel = tw.create_docset_tool(query='cql:[word="Merkel"]')["docset_id"]
    ergebnis = tw.keyness_tool(target_docset_id=ziel, sort_by="ll_signed", min_freq=5)
    sicht = extract_raw_surface(ergebnis, werkzeug="keyness")["rows"][0]
    for pflicht in (
        "target_per_million",
        "reference_per_million",
        "log_ratio",
        "lrc",
        "low_reliability",
    ):
        assert pflicht in sicht, (pflicht, list(sicht))
    # direction bleibt: claim_rules/keyness.py liest es AUS DER OBERFLAECHE.
    assert "direction" in sicht
    # Und die Rate ist aus Rohwert und Nenner der Antwort herstellbar.
    nenner = ergebnis["diagnostics"]["target_tokens"]
    erwartet = sicht["target_freq"] * 1_000_000.0 / nenner
    assert abs(erwartet - sicht["target_per_million"]) < 1e-3


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_logdice_ist_aus_der_modellsicht_nachrechenbar():
    from candyconc.candyconc_copilot.grounding_evidence import extract_raw_surface

    ergebnis = tw.collocate_stats_tool(term="Menschen", sort_by="logdice")
    knoten = ergebnis["node_frequency"]
    sicht = extract_raw_surface(ergebnis, werkzeug="collocate_stats")["rows"][0]
    assert "f2" in sicht, list(sicht)
    von_hand = 14.0 + math.log2(
        2.0 * sicht["f"] / (float(knoten) + float(sicht["f2"]))
    )
    assert abs(von_hand - sicht["logdice"]) < 5e-4, (von_hand, sicht)


@needs_bench
@pytest.mark.usefixtures("active_index")
def test_f2_steht_auf_BEIDEN_flaechen(active_index):  # noqa: F811
    """Zwei keep-Listen, Copilot und REST. Eine allein waere eine Drift."""
    from fastapi.testclient import TestClient
    from candyconc.services.backend import server

    server.set_default_index(active_index)
    klient = TestClient(server.app)
    antwort = klient.get(
        "/api/v1/analysis/collocates",
        params={"term": "Menschen", "sort_by": "logdice", "window": 5},
    )
    assert antwort.status_code == 200, antwort.text[:200]
    rest = (antwort.json().get("rows") or antwort.json().get("results") or [])[0]
    copilot = tw.collocate_stats_tool(term="Menschen", sort_by="logdice")["rows"][0]
    assert "f2" in rest and "f2" in copilot
    assert rest["f2"] == copilot["f2"]
    assert rest["logdice"] == copilot["logdice"]


def test_ein_werkzeug_ohne_vertrag_behaelt_sein_verhalten():
    """Der Vertrag ist eine Erweiterung, keine stille Umstellung fuer alle."""
    from candyconc.candyconc_copilot.grounding_evidence import _surface_row_dict

    zeile = {"word": "x", "f": 3, "irgendwas": 1, "noch_eins": 2}
    assert _surface_row_dict(zeile, werkzeug="kwic") == _surface_row_dict(zeile)
    assert "kwic" not in FELDVERTRAEGE

@needs_bench
@pytest.mark.usefixtures("active_index")
def test_der_vertrag_kuerzt_die_darstellung_nicht_die_beweislage():
    """Die unbeschraenkte Belegaufzeichnung bleibt vollstaendig.

    Beim ersten Anlauf griff der Vertrag AUCH auf ``fact_surface``, die
    Aufzeichnung mit ``bounded=False``, gegen die spaeter geprueft wird.
    Damit verschwand zum Beispiel ``delta_p_cn`` aus der Beweislage, obwohl
    es nur aus der Darstellung verschwinden sollte. Eine Zahl, die das
    Modell nicht zitieren soll, muss trotzdem nachweisbar bleiben, sonst
    kuerzt eine Darstellungsentscheidung still die Verifikation.
    """
    from candyconc.candyconc_copilot.grounding_evidence import extract_raw_surface

    ergebnis = tw.collocate_stats_tool(term="Menschen", sort_by="logdice")
    knapp = extract_raw_surface(ergebnis, werkzeug="collocate_stats")["rows"][0]
    voll = extract_raw_surface(
        ergebnis, bounded=False, werkzeug="collocate_stats"
    )["rows"][0]
    for weggelassen in ("delta_p_cn", "delta_p_nc", "mi3", "logdice_window"):
        assert weggelassen not in knapp, weggelassen
        assert weggelassen in voll, (
            f"{weggelassen} fehlt in der Belegaufzeichnung. Der Vertrag "
            "darf nur die Modellsicht bestimmen."
        )
