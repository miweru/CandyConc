"""Parallel KWIC reads mmap-backed metadata consistently with the REST path."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import SimpleNamespace

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()


class _MetadataMapping(Mapping[int, dict[str, object]]):
    """Wie der mmap-Speicher, ohne sich als dict auszugeben."""

    def __init__(self, values: dict[int, dict[str, object]]) -> None:
        self._values = values

    def __getitem__(self, key: int) -> dict[str, object]:
        return self._values[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def test_werkzeug_findet_das_original_eines_ki_treffers(monkeypatch):
    from candyconc.services.backend import server as srv

    idx = SimpleNamespace(
        fast_index=SimpleNamespace(
            doc_metadata=_MetadataMapping({
                0: {"doc_id": "0", "model": "human", "text_type": "human", "path": "original.txt"},
                1: {"doc_id": "1", "ref_doc": 0, "model": "ki", "text_type": "ai", "path": "fassung.txt"},
            }),
            doc_path_for_idx=lambda doc_id: f"doc-{doc_id}.txt",
        )
    )
    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: idx)
    monkeypatch.setattr(srv, "_paired_guard", lambda *_args: None)
    monkeypatch.setattr(srv, "_tokenize_kw", lambda _keyword: ["Hase"])
    monkeypatch.setattr(srv, "_doc_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_sentence_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_doc_id_for_position", lambda *_args: 1)
    monkeypatch.setattr(srv, "_sentence_bounds_for_doc", lambda *_args, **_kwargs: [0])
    monkeypatch.setattr(srv, "_sentence_index_for_pos", lambda *_args: 0)
    monkeypatch.setattr(srv, "_sentence_data_for_indices", lambda *_args, **_kwargs: [{"index": 0}])
    monkeypatch.setattr(srv, "resolve_pair_groups", lambda *_args, **_kwargs: {0: [0, 1]})
    monkeypatch.setattr(srv, "_best_matching_sentence", lambda *_args, **_kwargs: ({"index": 0}, 1, 0.1, 0.9))
    monkeypatch.setattr(
        srv, "_kwic_from_sentence",
        lambda *_args, **_kwargs: {"left": "Der", "kw": "Hase", "right": "springt", "matched": True},
    )

    ergebnis = _TW.parallel_kwic_tool(pos=6, keyword="Hase", include_models=["human"])

    assert ergebnis["ref_doc"] == 0, "ref_doc fiel auf das Dokument selbst zurueck."
    assert ergebnis["base_doc_id"] == 1
    assert [(v["doc_id"], v["model"], v["text_type"]) for v in ergebnis["variants"]] == [(0, "human", "human")]
