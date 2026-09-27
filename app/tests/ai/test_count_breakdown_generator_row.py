"""Generator summaries combine counts and denominators without changing dispersion."""

from __future__ import annotations

import numpy as np
import pytest

from candyconc.candyconc_copilot import count_breakdown as cb

WERTE = ["a_generator_lmstudio", "b_generator_single", "c_direct_improvement"]
TREFFER = {0: 2, 2: 4, 4: 10}


class _Index:
    def metadata_values(self, feld, filters=None):
        return list(WERTE)


@pytest.fixture
def aufschluesselung(monkeypatch):
    ids = {wert: np.array([2 * i, 2 * i + 1]) for i, wert in enumerate(WERTE)}
    monkeypatch.setattr(cb, "ids_mit_filtern", lambda idx, filters, basis, *, server: ids[next(
        v for k, v in filters.items())])
    monkeypatch.setattr(cb, "nenner", lambda idx, i: {"woerter": 200, "roh": 250})
    monkeypatch.setattr(cb, "_zaehler", lambda idx, query, ci, server: (lambda i: TREFFER[int(i[0])]))

    def aufrufen(nach):
        return cb.zeilen(_Index(), "x", nach=nach, filters=None, basis=None, case_insensitive=True, server=None)

    return aufrufen


def test_nach_verfahren_steht_die_generatorzeile_am_ende(aufschluesselung):
    ergebnis = aufschluesselung("prompting_method")
    zusammen = ergebnis["rows"][-1]
    assert zusammen["wert"] == cb.GENERATORZEILE
    assert zusammen["total"] == 6 and zusammen["tokens"] == 400 and zusammen["docs"] == 4
    assert zusammen["per_million"] == 15000.0
    assert zusammen["procedures"] == {"a_generator_lmstudio": 2, "b_generator_single": 2}
    assert "share" not in zusammen


def test_die_streuung_gilt_nur_den_werten_des_feldes(aufschluesselung):
    ergebnis = aufschluesselung("variant")
    assert len(ergebnis["rows"]) == 4
    assert ergebnis["dp_nach"] == cb.streuung(ergebnis["rows"][:3])["dp_nach"]


def test_nach_anderen_feldern_keine_generatorzeile(aufschluesselung):
    ergebnis = aufschluesselung("model")
    assert [z["wert"] for z in ergebnis["rows"]] == WERTE


def test_nur_generatoren_oder_einer_ergeben_keine_zeile():
    zwei = [{"wert": "a_generator", "total": 1, "tokens": 10, "docs": 1},
            {"wert": "b_generator", "total": 1, "tokens": 10, "docs": 1}]
    ids = [np.array([0]), np.array([1])]
    assert cb.generatorzeile(None, zwei, ids, None) is None
    einer = [zwei[0], {"wert": "original", "total": 1, "tokens": 10, "docs": 1}]
    assert cb.generatorzeile(None, einer, ids, None) is None
