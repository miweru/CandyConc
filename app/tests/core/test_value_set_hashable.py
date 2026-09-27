"""Eine Wertmenge im Token-Filter macht den Abfrageknoten nicht unhashbar.

Pilotlauf 2026-09-16, zehn Ausfaelle in beiden Messarmen:

    [word="zudem"] []{1,40} [word in {"außerdem","ferner","zusätzlich"}]

    TypeError: unhashable type: 'list'
      cqlhpc/engine.py in _sentence_filter_ids_for_node
        cached = memo.get(node, _CACHE_MISSING)

``Cond`` ist ``@dataclass(frozen=True, slots=True)`` und dient als
Cache-Schluessel. Sein eigener Docstring verlangt einen hashbaren Wert
(ast.py: "plain string so the field stays hashable for cache keys").
``parse_set_literal`` lieferte aber eine ``list``.

Warum es erst spaet auffiel: gehasht wird nur im Memo des Satzfilters.
Dieselbe Mengenbedingung ohne Satzkontext lief durch.

Die Pruefung in ``parse_set_literal`` faengt seit jeher die VERSCHACHTELTE
Menge (Liste in Liste). Die aeussere Liste blieb eine Liste, ein Fix an
einer von zwei Naehten.
"""
from __future__ import annotations

import pytest

from cqlhpc.parser import parse_cql as parse


def _conds(knoten):
    """Alle Cond-Objekte eines Abfragebaums einsammeln."""
    gefunden = []
    stapel = [knoten]
    while stapel:
        k = stapel.pop()
        for feld in ("parts", "options"):
            teil = getattr(k, feld, None)
            if teil:
                stapel.extend(teil)
        for feld in ("clause", "node", "inner"):
            teil = getattr(k, feld, None)
            if teil is not None:
                stapel.append(teil)
        conds = getattr(k, "conds", None)
        if conds:
            gefunden.extend(conds)
    return gefunden


def test_wertmenge_macht_den_knoten_nicht_unhashbar():
    knoten = parse('[word in {"außerdem","ferner","zusätzlich"}]')
    hash(knoten)  # der echte Ausfall: TypeError: unhashable type: 'list'


def test_die_abfrage_des_pilotlaufs_ist_hashbar():
    knoten = parse('[word="zudem"] []{1,40} [word in {"außerdem","ferner"}]')
    memo = {}
    memo[knoten] = "irgendwas"
    assert memo[knoten] == "irgendwas"


def test_der_wert_bleibt_eine_folge_mit_denselben_elementen():
    conds = _conds(parse('[word in {"a","b","c"}]'))
    assert len(conds) == 1
    c = conds[0]
    assert c.op == "in"
    assert list(c.value) == ["a", "b", "c"]


def test_verschachtelte_menge_bleibt_eine_eingabefrage():
    from cqlhpc.parser import ParseError

    with pytest.raises(ParseError):
        parse('[word in {"a", {"b"}}]')
