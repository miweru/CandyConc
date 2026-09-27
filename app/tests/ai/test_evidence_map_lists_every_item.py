# -*- coding: utf-8 -*-
"""The evidence map lists every element that a citation chip can address."""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as modul


class _Bus:
    def __init__(self):
        self.ereignisse = []

    def publish(self, ereignis, session_id=""):
        self.ereignisse.append(ereignis)


class _Orch:
    session = type("S", (), {"session_id": "s1"})()


def test_every_evidence_item_reaches_the_chip_map():
    items = [{"id": f"E_query_count_{i}", "tool": "query_count",
              "query": f'{{"query": "w{i}"}}', "status": "success"} for i in range(1, 36)]
    bus = _Bus()
    modul._publiziere_belegkarte(_Orch(), bus, items)
    karte = bus.ereignisse[0]["grounding"]["evidence"]
    assert [e["id"] for e in karte] == [f"E_query_count_{i}" for i in range(1, 36)]
