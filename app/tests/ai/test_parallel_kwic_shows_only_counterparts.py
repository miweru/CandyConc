"""Parallel KWIC shows actual counterparts and highlights only the query term."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from types import SimpleNamespace

import pytest

from candyconc.services.backend import server as srv
from candyconc.services.backend.server import SentenceData, _align_sentence_lists
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()

_ORIGINAL = "Die Regierung hat allerdings keinen Plan vorgelegt ."
_FASSUNGEN = {
    # doc_id: (Modell, Satz)
    1: ("a-nah", "Die Regierung hat allerdings noch keinen Plan vorgelegt ."),
    2: ("b-ohne-stichwort", "Die Regierung hat jedoch keinen Plan vorgelegt ."),
    # Umgestellt: Editaehnlichkeit 0,33, die Dokumentausrichtung paart den
    # Satz ueber die Wortueberlappung (0,8). Unterscheidet "dasselbe
    # Kriterium" von einer Schwelle allein auf der Editaehnlichkeit.
    3: ("c-umgestellt", "Einen Plan hat die Regierung allerdings nicht vorgelegt ."),
    4: ("d-fremd", "Im Winter halten Kreuzottern eine Winterstarre ."),
}


def _satz(doc_id: int, text: str) -> SentenceData:
    woerter = text.split()
    start = doc_id * 100
    return SentenceData(index=0, start_pos=start, end_pos=start + len(woerter), text=text, tokens=woerter)


_SAETZE = {0: _satz(0, _ORIGINAL), **{d: _satz(d, s) for d, (_m, s) in _FASSUNGEN.items()}}


class _Metadaten(Mapping[int, dict[str, object]]):
    def __init__(self, werte: dict[int, dict[str, object]]) -> None:
        self._werte = werte

    def __getitem__(self, key: int) -> dict[str, object]:
        return self._werte[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._werte)

    def __len__(self) -> int:
        return len(self._werte)


@pytest.fixture
def gepaart(monkeypatch):
    metadaten = {0: {"doc_id": "0", "model": "human", "text_type": "human", "path": "original.txt"}}
    for doc_id, (modell, _satz_text) in _FASSUNGEN.items():
        metadaten[doc_id] = {"doc_id": str(doc_id), "ref_doc": "0", "model": modell,
                             "text_type": "ai", "path": f"fassung{doc_id}.txt"}
    idx = SimpleNamespace(fast_index=SimpleNamespace(
        doc_metadata=_Metadaten(metadaten), doc_path_for_idx=lambda doc_id: f"doc-{doc_id}.txt"))
    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: idx)
    monkeypatch.setattr(srv, "_paired_guard", lambda *_args: None)
    monkeypatch.setattr(srv, "_doc_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_sentence_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_doc_id_for_position", lambda *_args: 0)
    # Je Dokument ein Satz. Ausrichtung und KWIC-Bau bleiben die echten Funktionen.
    monkeypatch.setattr(srv, "_sentence_bounds_for_doc", lambda _idx, doc_id, **_kw: [(doc_id * 100, doc_id * 100 + 12)])
    monkeypatch.setattr(srv, "_sentence_index_for_pos", lambda *_args: 0)
    monkeypatch.setattr(srv, "_sentence_data_for_indices", lambda _idx, doc_id, _bounds, _indices: [_SAETZE[int(doc_id)]])
    monkeypatch.setattr(srv, "resolve_pair_groups", lambda *_args, **_kwargs: {0: [0, 1, 2, 3, 4]})

    async def _gleich(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(srv, "_run_heavy_scan", _gleich)
    return idx


def _rest():
    ergebnis = asyncio.run(srv.analysis_kwic_parallel(
        {"corpus": "paired", "pos": 3, "keyword": "allerdings", "ctx": 6, "max_variants": 6}))
    return ergebnis["variants"]


def _werkzeug():
    return _TW.parallel_kwic_tool(pos=3, keyword="allerdings", ctx=6, max_variants=6)["variants"]


@pytest.mark.parametrize("weg", [_rest, _werkzeug], ids=["rest", "werkzeug"])
def test_ein_satz_unter_der_schwelle_ist_kein_gegenstueck(gepaart, weg):
    fassungen = {v["doc_id"]: v for v in weg()}
    assert sorted(fassungen) == [1, 2, 3, 4], "Keine Fassung verschwindet still."
    fremd = fassungen[4]
    assert fremd["aligned"] is False
    assert (fremd["left"], fremd["kw"], fremd["right"]) == ("", "", "")
    assert (fremd["med"], fremd["norm_med"], fremd["similarity"]) == (None, None, None)
    assert all(fassungen[d]["aligned"] is True for d in (1, 2, 3))


@pytest.mark.parametrize("weg", [_rest, _werkzeug], ids=["rest", "werkzeug"])
def test_in_der_klammer_steht_nur_das_stichwort(gepaart, weg):
    fassungen = {v["doc_id"]: v for v in weg()}
    for doc_id in (1, 3):
        assert fassungen[doc_id]["matched"] is True
        assert fassungen[doc_id]["kw"] == "allerdings"
    ohne = fassungen[2]
    assert ohne["matched"] is False
    assert ohne["kw"] == "", "Fehlt das Stichwort, bleibt die Klammer leer."
    # Der Satz bleibt sichtbar, kein Token geht verloren.
    assert f'{ohne["left"]} {ohne["right"]}'.split() == _FASSUNGEN[2][1].split()


@pytest.mark.parametrize("weg", [_rest, _werkzeug], ids=["rest", "werkzeug"])
def test_dasselbe_kriterium_wie_die_dokumentausrichtung(gepaart, weg):
    for fassung in weg():
        paare, _bilanz = _align_sentence_lists([_SAETZE[0]], [_SAETZE[fassung["doc_id"]]])
        gegenstueck = [p for p in paare if p["ref_index"] is not None and p["var_index"] is not None]
        assert fassung["aligned"] is bool(gegenstueck), fassung
        if gegenstueck:
            assert fassung["similarity"] == pytest.approx(gegenstueck[0]["similarity"])


def test_rest_und_werkzeug_liefern_dieselben_fassungen(gepaart):
    assert _rest() == _werkzeug()
