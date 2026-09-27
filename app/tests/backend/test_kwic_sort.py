"""W1: KWIC sort (P0 #1) — pure sort transform."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.services.backend.kwic_renderer import (  # noqa: E402
    parse_sort,
    sort_kwic_rows,
)


def _row(left, kw, right, pos, **meta):
    r = {"left": left, "kw": kw, "right": right, "pos": pos}
    if meta:
        r["meta"] = meta
    return r


ROWS = [
    _row("a b zeta", "Haus", "alpha beta", 10, source="news"),
    _row("a b alpha", "Haus", "zeta gamma", 20, source="blog"),
    _row("a b mitte", "Haus", "mitte mitte", 30, source="news"),
]


def test_parse_sort():
    assert parse_sort(None) is None
    assert parse_sort("") is None
    assert parse_sort("position") is None
    assert parse_sort("1L") == ("1l", "")
    assert parse_sort("node") == ("node", "")
    assert parse_sort("3R") == ("3r", "")
    assert parse_sort("meta:source") == ("meta", "source")
    with pytest.raises(ValueError):
        parse_sort("meta:")
    with pytest.raises(ValueError):
        parse_sort("bogus")


def test_sort_1l_immediate_left():
    # 1L = token immediately left of node: "zeta","alpha","mitte" -> alpha,mitte,zeta
    out = sort_kwic_rows(ROWS, "1L")
    assert [r["pos"] for r in out] == [20, 30, 10]


def test_sort_1r_immediate_right():
    # 1R = first right token: "alpha","zeta","mitte" -> alpha,mitte,zeta
    out = sort_kwic_rows(ROWS, "1R")
    assert [r["pos"] for r in out] == [10, 30, 20]


def test_sort_desc():
    out = sort_kwic_rows(ROWS, "1L", sort_dir="desc")
    assert [r["pos"] for r in out] == [10, 30, 20]


def test_sort_meta_field():
    out = sort_kwic_rows(ROWS, "meta:source")
    # blog < news; the two news rows keep position order (stable secondary key)
    assert [r["pos"] for r in out] == [20, 10, 30]


def test_sort_none_returns_same_list_object():
    out = sort_kwic_rows(ROWS, None)
    assert out is ROWS  # no-op identity for the default path


def test_sort_german_collation_umlaut():
    rows = [
        _row("x", "n", "Äpfel", 1),
        _row("x", "n", "Apfel", 2),
        _row("x", "n", "Birne", 3),
    ]
    out = sort_kwic_rows(rows, "1R")
    # ä folds to a -> Apfel/Äpfel before Birne (stable: Äpfel(1) then Apfel(2) tie on 'a*')
    assert out[-1]["right"] == "Birne"
    assert {out[0]["right"], out[1]["right"]} == {"Äpfel", "Apfel"}


def test_sort_missing_context_token_sorts_first():
    rows = [_row("", "n", "", 1), _row("a b c", "n", "z", 2)]
    out = sort_kwic_rows(rows, "1L")
    assert out[0]["pos"] == 1  # empty key sorts first ascending
