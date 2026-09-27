# -*- coding: utf-8 -*-
"""A negated top-N heading does not promise a table with N rows."""

from __future__ import annotations

from candyconc.candyconc_copilot import table_promise_check as zusage


def _tabelle(kopf: str, zeilen: int) -> str:
    koerper = "\n".join(f"|{13 + i}|{1000 - i}|" for i in range(zeilen))
    return f"{kopf}\n\n| Länge | Treffer |\n|---|---|\n{koerper}\n"


def test_negated_top_100_heading_promises_nothing():
    kopf = "### 1. Vollzählige Serie ab 13 Buchstaben — kein Top-100-Ausschnitt"
    assert zusage.luecken(_tabelle(kopf, 34)) == []


def test_a_real_top_10_heading_still_holds_its_promise():
    kopf = "### ll-Top-10 (4.672)"
    assert zusage.luecken(_tabelle(kopf, 9)) == [(kopf, 10, 9)]
