"""Dispersion evidence includes dp_min, dp_erwartet and dp_max.

Compute dispersion from document boundaries and pass the tool-shaped
result through the production evidence path."""

from __future__ import annotations

import json

import numpy as np

from candyconc.analysis_defaults import summarize_dispersion_offsets
from candyconc.candyconc_copilot.interpretation_synthesis import evidenz_paket_text
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
from candyconc.candyconc_copilot.method_sheet import _analysis_provenance_lines
from tests.ai._real_copilot import _MODULES as _REAL_MODULES

_tool_output_for_model = _REAL_MODULES["candyconc_copilot.orchestrator"]._tool_output_for_model

REFERENZ = ("dp_min", "dp_erwartet", "dp_max")


def _dispersion_wie_das_werkzeug() -> dict:
    """2.000 ungleich lange Dokumente, 300 Treffer in 40 davon gebündelt."""
    rng = np.random.default_rng(7)
    groessen = rng.integers(20, 400, size=2000)
    grenzen = np.concatenate([[0], np.cumsum(groessen)[:-1]]).astype(np.int64)
    token = int(groessen.sum())
    treffer = []
    for dok in range(40):
        anfang = int(grenzen[dok])
        treffer.extend(anfang + (np.arange(7) * 3 % int(groessen[dok])))
    treffer = np.asarray(sorted(set(int(t) for t in treffer))[:300], dtype=np.int64)
    profil = summarize_dispersion_offsets(treffer, token_count=token, doc_bounds=grenzen)
    for nur_rest in ("classification", "peak_dominated", "peak_partition_local"):
        profil.pop(nur_rest, None)
    return {"status": "success", "term": "Probe", "offsets": treffer.tolist(), **profil}


def _item(ausgabe: dict):
    return make_evidence_item(
        item_id="E_dispersion_offsets_1",
        tool="dispersion_offsets",
        tool_call_id="c1",
        query=json.dumps({"term": "Probe"}),
        output=ausgabe,
        analysis_family="dispersion",
    )


def test_reference_values_are_computed_by_the_tool_path():
    ausgabe = _dispersion_wie_das_werkzeug()
    for feld in REFERENZ:
        assert isinstance(ausgabe.get(feld), float), (feld, ausgabe.get(feld))
    assert ausgabe["dp_min"] <= ausgabe["dp_erwartet"] <= ausgabe["dp_max"]


def test_reference_values_reach_raw_and_fact_surface():
    ausgabe = _dispersion_wie_das_werkzeug()
    item = _item(ausgabe)
    for feld in REFERENZ:
        assert item.raw_surface.get(feld) == ausgabe[feld], feld
        assert item.fact_surface.get(feld) == ausgabe[feld], feld
        assert any(zeile.startswith(f"{feld}=") for zeile in item.grounding_surface), feld


def test_compacted_model_view_shows_reference_values():
    ausgabe = _dispersion_wie_das_werkzeug()
    # Echte Dispersionen sind Millionen Zeichen groß, die Sicht ist dann die Belegfläche.
    ausgabe["doc_sizes"] = ausgabe["doc_sizes"] * 20
    sicht = _tool_output_for_model(ausgabe, werkzeug="dispersion_offsets")
    assert sicht.get("model_view_compacted") is True
    for feld in REFERENZ:
        assert sicht["evidence"].get(feld) == ausgabe[feld], feld


def test_provenance_reads_dp_against_its_reference():
    ausgabe = _dispersion_wie_das_werkzeug()
    zeilen = " ".join(_analysis_provenance_lines([_item(ausgabe)]))
    assert "ohne Referenzwerte nicht deutbar" not in zeilen, zeilen
    assert "erreichbare Untergrenze" in zeilen, zeilen
    erwartet = f"{ausgabe['dp_erwartet']:.4f}".rstrip("0")
    assert erwartet[:5] in zeilen.replace(",", "."), (erwartet, zeilen)


def test_package_carries_reference_values(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_MAX_ZEICHEN", "300000")
    ausgabe = _dispersion_wie_das_werkzeug()
    paket = evidenz_paket_text([_item(ausgabe)])
    for feld in REFERENZ:
        assert f"{feld}={ausgabe[feld]}" in paket, (feld, paket)


def test_high_null_expectation_is_stated_against_the_profile():
    """Wenige Treffer auf viele Dokumente: dp_erwartet über 0,8 wie am Testindex.

    Der Zweig war am echten Pfad nie erreicht. Scharf geschaltet darf er nicht
    behaupten, das Profil werde am festen Schnittpunkt vergeben, denn
    _dispersion_profile_label misst an dp_erwartet.
    """
    rng = np.random.default_rng(11)
    groessen = rng.integers(20, 400, size=20000)
    grenzen = np.concatenate([[0], np.cumsum(groessen)[:-1]]).astype(np.int64)
    treffer = np.sort(rng.choice(int(groessen.sum()), size=300, replace=False)).astype(np.int64)
    profil = summarize_dispersion_offsets(treffer, token_count=int(groessen.sum()), doc_bounds=grenzen)
    assert profil["dp_erwartet"] >= 0.8, profil["dp_erwartet"]
    ausgabe = {"status": "success", "term": "Probe", "offsets": treffer.tolist(), **profil}
    zeilen = " ".join(_analysis_provenance_lines([_item(ausgabe)]))
    assert "ohne Referenzwerte nicht deutbar" not in zeilen, zeilen
    assert "Das Profil misst deshalb die Lage zu diesem Erwartungswert" in zeilen, zeilen
    assert "ab dem das Profil `strongly_clustered` vergeben wird" not in zeilen, zeilen
