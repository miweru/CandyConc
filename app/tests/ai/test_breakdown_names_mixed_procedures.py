"""A breakdown row combining several procedures names each procedure."""

from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

from candyconc.candyconc_copilot import count_breakdown as cb

#: Modell, Verfahren und Dokumente wie in easy_language, verkleinert auf je drei.
_DOKUMENTE = [
    ("human", "original", 3),
    ("claude-opus-4-7", "claude_opus_4_7_generator", 3),
    ("gemma-4-26b-a4b-it-qat-lmstudio", "gemma_4_26b_a4b_it_qat_generator_lmstudio", 3),
    ("mistral-small-4-119b-2603", "mistral_small_4_119b_generator_lmstudio", 3),
    ("gpt-5.5", "gpt_5_5_generator_single_subagent", 3),
    ("gpt-5.5", "gpt_5_5_direct_improvement_single_subagent", 3),
]


def _index():
    meta, d = {}, 0
    for modell, verfahren, anzahl in _DOKUMENTE:
        for _ in range(anzahl):
            meta[d] = {"model": modell, "variant": verfahren, "register": "easy_language"}
            d += 1

    def metadata_values(feld, filters=None):
        return sorted({m[feld] for m in meta.values()})

    return SimpleNamespace(
        metadata_values=metadata_values,
        fast_index=SimpleNamespace(
            doc_metadata=meta,
            boundaries=SimpleNamespace(document=SimpleNamespace(_positions=np.arange(d)))),
    ), meta


@pytest.fixture()
def aufgeschluesselt(monkeypatch):
    idx, meta = _index()

    # server: the backend module the caller passes in (import contract), unused here.
    def ids_mit_filtern(_idx, filters, _basis, *, server):
        return np.array([d for d, m in meta.items()
                         if all(m.get(k) == v for k, v in filters.items())], dtype=np.uint32)

    monkeypatch.setattr(cb, "ids_mit_filtern", ids_mit_filtern)
    monkeypatch.setattr(cb, "_zaehler", lambda *_a: (lambda ids: 2 * int(len(ids))))
    monkeypatch.setattr(cb, "nenner", lambda _idx, ids: {"woerter": 1000 * len(ids), "roh": 1200 * len(ids)})

    def zeilen(nach):
        return {z["wert"]: z for z in cb.zeilen(idx, "q", nach=nach, filters=None, basis=None,
                                                case_insensitive=True, server=SimpleNamespace())["rows"]}

    return zeilen


def test_die_mischzeile_nennt_ihre_verfahren(aufgeschluesselt):
    zeilen = aufgeschluesselt("model")
    assert zeilen["gpt-5.5"]["docs"] == 6
    assert zeilen["gpt-5.5"]["procedures"] == {
        "gpt_5_5_direct_improvement_single_subagent": 3,
        "gpt_5_5_generator_single_subagent": 3,
    }


def test_reine_zeilen_bleiben_ohne_verfahrensangabe(aufgeschluesselt):
    zeilen = aufgeschluesselt("model")
    for wert in ("human", "claude-opus-4-7", "gemma-4-26b-a4b-it-qat-lmstudio"):
        assert "procedures" not in zeilen[wert], zeilen[wert]


def test_nach_variant_braucht_keine_angabe(aufgeschluesselt):
    assert not any("procedures" in z for z in aufgeschluesselt("variant").values())


def test_wo_alle_zeilen_mischen_ist_nichts_eine_ausnahme():
    # nach register: jede Zeile umfasst dieselben Verfahren.
    codes = np.array([0, 1, 2, 0, 1, 2])
    je_zeile = cb.mischverfahren([np.array([0, 1, 2]), np.array([3, 4, 5])], codes, ["a", "b", "c"])
    assert je_zeile == [None, None]


def test_zwei_zeilen_mit_einer_reinen_sind_keine_mehrheit():
    # nach text_type: human rein, ai mischt alle Generatoren.
    codes = np.array([0, 1, 2, 3])
    je_zeile = cb.mischverfahren([np.array([0]), np.array([1, 2, 3])], codes, ["o", "g1", "g2", "g3"])
    assert je_zeile == [None, None]


def test_das_feld_erreicht_schema_vertrag_und_kern():
    from candyconc.candyconc_copilot.grounding_field_contract import FELDVERTRAEGE
    from candyconc.candyconc_copilot.prompt_layout import build_static_core
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    assert "procedures" in FELDVERTRAEGE["query_count"]
    zeile = _load_real_tool_wrappers().QUERY_COUNT_RESPONSE["properties"]["rows"]["items"]
    assert zeile["properties"]["procedures"]["additionalProperties"] == {"type": "integer"}
    assert "procedures: Dokumente je variant" in build_static_core()


def test_ein_korpus_mit_einem_verfahren_bleibt_unveraendert():
    from candyconc.core.corpus_index import CorpusIndex

    pfad = os.environ.get("CANDYCONC_INDEX_PATH")
    if not pfad or not os.path.isdir(pfad):
        pytest.skip("CANDYCONC_INDEX_PATH zeigt nicht auf einen Index")
    idx = CorpusIndex(pfad)
    if len(idx.metadata_values("variant") or []) > 1:
        pytest.skip("der Index trägt mehrere Verfahren")
    assert cb._verfahrenscodes(idx) is None
