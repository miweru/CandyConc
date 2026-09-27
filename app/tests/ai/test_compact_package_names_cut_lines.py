# -*- coding: utf-8 -*-
"""Die knappe Paketform nennt Belegzeilen, die an der Kappe von zwoelf fallen.

Methodenbefund C9 der Session CandyConc Paper (2026-09-26, nachweise/
methoden.md, Abschnitt 17.3): weitere substantielle Zeilen hoechstens 12 je
Posten, ohne Hinweis. Die ausfuehrliche Form nannte das schon („(… N weitere
Belegzeilen dieses Elements liegen vor und sind hier gekuerzt)“), die knappe,
seit 107 die Vorgabe, nicht.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as ds


def _posten(n: int) -> dict:
    return {"id": "E_word_sketch_3", "tool": "word_sketch", "status": "success",
            "query": "Herausforderung",
            "grounding_surface": [f"rows[{i}] relation=obj word=Wort{i} f={100 - i}" for i in range(n)]}


def test_compact_form_names_the_lines_it_cuts(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    text = ds.evidenz_paket_text([_posten(20)])
    assert "rows[11]" in text and "rows[12]" not in text
    assert "(… 8 weitere Belegzeilen dieses Elements liegen vor und sind hier gekuerzt)" in text


def test_no_note_when_nothing_is_cut(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    assert "weitere Belegzeilen" not in ds.evidenz_paket_text([_posten(10)])
