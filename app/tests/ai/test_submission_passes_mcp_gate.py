# -*- coding: utf-8 -*-
"""Interpretation submission passes the MCP boundary."""

import asyncio
import json

import pytest
from fastapi import HTTPException

from candyconc.services.mcp_server import (
    _is_product_tool_visible,
    _product_tool_bindings,
    execute_tool_call,
)


@pytest.fixture(scope="module", autouse=True)
def _echtes_werkzeug_in_der_registry():
    """Der Conftest-Stub ersetzt tool_wrappers durch ein Modul ohne
    Registrierungen. Fuer diese Probe kommt das ECHE Werkzeug in die
    Registry: geladen ueber den Parity-Loader, angemeldet mit dem
    echten Dekorator, dann kann die Naht gefunden und passiert
    werden. Nach der Probe wird der Eintrag WIEDER ENTFERNT — eine
    geliehene Registrierung darf nicht in die Security-Tests sickern
    (gemessen: 18 rote test_mcp_security nach dem ersten Lauf)."""
    from candyconc.tooling.registry import REGISTRY, llm_tool
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    tw = _load_real_tool_wrappers()
    llm_tool(tw.DEUTUNG_ABGEBEN_TOOL)(tw.deutung_abgeben_tool)
    yield
    REGISTRY[:] = [
        eintrag
        for eintrag in REGISTRY
        if eintrag.get("function", {}).get("name") != "deutung_abgeben"
    ]

VOLLE_ABGABE = {
    "name": "deutung_abgeben",
    "arguments": {
        "beantwortet": (
            "Die Belegzahl des Begriffs ist am Index verifiziert: "
            "Korpus gesamt 1093, menschliche Originale 127, "
            "KI-Fassungen 966."
        ),
        "belege": ["E_query_count_1", "E_query_count_2", "E_query_count_3"],
        "offen": "Das Kuerzel K.I. wurde nicht separat isoliert.",
    },
}


def test_die_abgabe_kommt_durch_die_naht():
    try:
        ergebnis = asyncio.run(execute_tool_call(dict(VOLLE_ABGABE), None))
    except HTTPException as exc:
        pytest.fail(f"Die 403-Wand steht noch: {exc.status_code} {exc.detail}")
    assert "MCP Fehler" not in json.dumps(ergebnis), ergebnis


def test_der_gate_eintrag_ist_eng():
    """Die Freistellung gilt fuer Turn-Steuerung, nicht fuer alles; die
    Produktliste selbst bleibt unberuehrt."""
    from candyconc.tooling.tool_selection import ist_turn_steuerung

    assert ist_turn_steuerung("deutung_abgeben")
    assert not ist_turn_steuerung("zzq_gibtsnicht")
    assert not _is_product_tool_visible("deutung_abgeben"), (
        "Die Abgabe ist Turn-Steuerung, sie gehoert NICHT in die "
        "sichtbare Produktflaeche."
    )


def test_die_produktflaeche_waechst_nicht():
    """Der Kapabilitaetsvertrag selbst bleibt unberuehrt: die Abgabe ist
    Turn-Steuerung und gehoert NICHT in die sichtbare Produktflaeche."""
    assert not _product_tool_bindings().get("deutung_abgeben")


def test_unbekanntes_werkzeug_bleibt_abgewiesen():
    with pytest.raises(HTTPException) as ctx:
        asyncio.run(
            execute_tool_call({"name": "zzq_gibtsnicht", "arguments": {}}, None)
        )
    assert ctx.value.status_code in (403, 404)
