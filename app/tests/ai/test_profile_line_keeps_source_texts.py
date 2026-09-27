"""source_texts steht in der Profilzeile des Pakets vor den Achsen.

Das Paket kürzt eine Profilzeile bei 1.600 Zeichen am Ende
(deutungs_synthese, 4 mal PAKET_ZEILE_MAX). Das Profil kam in der Folge
doc_len, axes, source_texts, und die längste Profilzeile der Zyklen 6 und 8
lag bei 1.529 Zeichen. Ein Docset mit einer Achse mehr hätte die Zahl der
Quelltexte zuerst verloren, also genau die Angabe, die Regression für
Dublettenfragen nachgetragen hat.
"""

from __future__ import annotations

import json

from candyconc.candyconc_copilot.interpretation_synthesis import evidenz_paket_text
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item


def _lange_profilausgabe() -> dict:
    achsen = {
        f"feld_{n:02d}": f"12 Werte, Tokenanteile: wert_a_{n} 10.4%, wert_b_{n} 10.3%, wert_c_{n} 10.0%, +9 weitere"
        for n in range(20)
    }
    return {
        "status": "success", "docset_id": "d" * 32, "doc_count": 5374, "token_count": 4000000,
        "label": "Treffer Herausforderung", "source": "query",
        "profile": {"doc_len": {"min": 1, "median": 331.0, "mean": 565.8, "max": 49923},
                    "axes": achsen, "source_texts": 3096},
    }


def _paket(monkeypatch, ausgabe):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_MAX_ZEICHEN", "300000")
    item = make_evidence_item(item_id="E_create_docset_1", tool="create_docset", tool_call_id="c1",
                              query=json.dumps({"query": "Herausforderung"}), output=ausgabe,
                              analysis_family="x")
    return evidenz_paket_text([item])


def test_long_profile_line_is_cut_but_keeps_source_texts(monkeypatch):
    paket = _paket(monkeypatch, _lange_profilausgabe())
    zeile = next(z for z in paket.splitlines() if z.strip().startswith("Profil:"))
    assert "Zeichen gekuerzt" in zeile, "die Probe muss die Kürzung auslösen"
    assert '"source_texts": 3096' in zeile, zeile[:300]
    assert '"doc_len"' in zeile


def test_axes_stay_in_the_profile_line(monkeypatch):
    ausgabe = _lange_profilausgabe()
    ausgabe["profile"]["axes"] = {"register": "10 Werte, Tokenanteile: news 30.0%, +9 weitere"}
    paket = _paket(monkeypatch, ausgabe)
    zeile = next(z for z in paket.splitlines() if z.strip().startswith("Profil:"))
    assert "Zeichen gekuerzt" not in zeile
    assert "register" in zeile and '"source_texts": 3096' in zeile


import os  # noqa: E402

import pytest  # noqa: E402

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw  # noqa: E402
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: E402,F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
def test_real_profile_puts_source_texts_before_axes(active_index):  # noqa: F811
    antwort = tw.create_docset_tool(filters={"split": "test"})
    schluessel = list(antwort["profile"])
    assert schluessel.index("source_texts") < schluessel.index("axes"), schluessel
    item = make_evidence_item(item_id="E_create_docset_1", tool="create_docset", tool_call_id="c1",
                              query=json.dumps({"filters": {"split": "test"}}), output=antwort,
                              analysis_family="x")
    zeile = next(z for z in item.grounding_surface if z.startswith("profile="))
    assert f"'source_texts': {antwort['profile']['source_texts']}" in zeile, zeile
