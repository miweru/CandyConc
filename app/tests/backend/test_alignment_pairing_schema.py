from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from types import SimpleNamespace

import pytest


def _sentence(index: int, tokens: list[str]):
    from candyconc.services.backend.server import SentenceData

    return SentenceData(
        index=index,
        start_pos=index * 1_000,
        end_pos=index * 1_000 + len(tokens),
        text=" ".join(tokens),
        tokens=tokens,
    )


def test_edit_alignment_scores_complete_sentences_never_a_truncated_prefix():
    """A matching prefix must not manufacture a 100 % sentence similarity."""
    from candyconc.services.backend.server import _align_sentence_lists

    reference = _sentence(0, ["gleich"] * 80 + ["referenz"] * 20)
    variant = _sentence(0, ["gleich"] * 80 + ["variante"] * 20)

    pairs, summary = _align_sentence_lists([reference], [variant], max_tokens=128)

    assert summary["aligned_pairs"] == 1
    assert pairs[0]["med"] == 20
    assert pairs[0]["similarity"] == pytest.approx(0.8)


def test_edit_alignment_refuses_a_sentence_above_the_exact_token_limit():
    from candyconc.services.backend.server import _align_sentence_lists

    sentence = _sentence(0, ["token"] * 81)
    pairs, status = _align_sentence_lists([sentence], [sentence], max_tokens=80)

    assert pairs == []
    assert status["status"] == "not_applicable"
    assert status["reason"] == "sentence_token_limit_exceeded"
    assert status["observed_tokens"] == 81


def test_edit_alignment_refuses_work_above_its_exact_budget_without_scoring_prefixes():
    from candyconc.services.backend.server import _align_sentence_lists

    reference = _sentence(0, ["referenz"] * 40)
    variant = _sentence(0, ["variante"] * 40)

    pairs, status = _align_sentence_lists(
        [reference],
        [variant],
        max_tokens=64,
        max_edit_cells=1_599,
    )

    assert pairs == []
    assert status["status"] == "not_applicable"
    assert status["reason"] == "exact_alignment_budget_exceeded"
    assert status["edit_cells"] == 1_600
    assert status["max_edit_cells"] == 1_599


def test_alignment_never_presents_a_weak_sentence_proposal_as_a_counterpart():
    """Unrelated sentences remain two gaps, never a plausible-looking diff."""
    from candyconc.services.backend.server import (
        _alignment_summary_from_pairs,
        _conservative_alignment_pairs,
    )

    weak_candidate = {
        "ref_index": 3,
        "var_index": 7,
        "ref_text": "Kreuzottern sind nicht wählerisch .",
        "var_text": "Im Winter halten Kreuzottern eine Winterstarre .",
        "ref_start": 30,
        "ref_end": 36,
        "var_start": 70,
        "var_end": 77,
        "med": 7,
        "similarity": 0.125,
        "norm_med": 0.875,
    }

    pairs = _conservative_alignment_pairs([weak_candidate])
    summary = _alignment_summary_from_pairs(pairs, alignment_cost=0.875)

    assert [(pair["ref_index"], pair["var_index"]) for pair in pairs] == [(3, None), (None, 7)]
    assert summary["aligned_pairs"] == 0
    assert summary["avg_similarity"] is None


def test_alignment_prefers_gaps_over_a_low_evidence_order_preserving_chain():
    """A split paraphrase must not shift every following sentence by one."""
    from candyconc.services.backend.server import _align_sentence_lists

    reference = [
        _sentence(0, [
            "Kreuzottern", "haben", "natürliche", "Feinde", "Dachse",
            "Füchse", "Wildschweine", "Igel", "Hauskatzen",
        ]),
        _sentence(1, ["Störche", "Kraniche", "Reiher", "Mäusebussarde", "Adler"]),
    ]
    variant = [
        _sentence(0, ["Kreuzottern", "haben", "viele", "natürliche", "Feinde"]),
        _sentence(1, [
            "Dazu", "gehören", "Dachse", "Füchse", "Wildschweine", "Igel",
            "auch", "Hauskatzen",
        ]),
    ]

    pairs, summary = _align_sentence_lists(reference, variant)

    assert [(pair["ref_index"], pair["var_index"]) for pair in pairs] == [
        (None, 0),
        (0, 1),
        (1, None),
    ]
    assert pairs[1]["similarity"] == pytest.approx(10 / 17)
    assert summary["aligned_pairs"] == 1


def test_parallel_group_summary_uses_declared_variant_axis_without_dropping_legacy_fields():
    from candyconc.services.backend import server as srv

    idx = SimpleNamespace(
        manifest=SimpleNamespace(pair_axes=["language"]),
        fast_index=SimpleNamespace(
            doc_metadata={
                10: {"text_type": "human", "language": "de", "path": "de.txt"},
                11: {"text_type": "translation", "language": "en", "path": "en.txt"},
                12: {"text_type": "translation", "language": "fr", "path": "fr.txt"},
            }
        ),
    )

    summary = srv._parallel_group_summary(idx, 10, [10, 11, 12])

    assert summary["human_doc_id"] == 10
    assert summary["variant_doc_ids"] == [11, 12]
    assert summary["models"] == [
        {"model": "en", "axis": "language", "axis_value": "en", "label": "en", "count": 1},
        {"model": "fr", "axis": "language", "axis_value": "fr", "label": "fr", "count": 1},
    ]
    assert summary["variants"] == [
        {"doc_id": 11, "label": "Dokument 11", "provenance": ""},
        {"doc_id": 12, "label": "Dokument 12", "provenance": ""},
    ]


class _MetadataMapping(Mapping[int, dict[str, object]]):
    """Mimics the mmap metadata store without pretending to be a dict."""

    def __init__(self, values: dict[int, dict[str, object]]) -> None:
        self._values = values

    def __getitem__(self, key: int) -> dict[str, object]:
        return self._values[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def test_parallel_kwic_reads_mapping_backed_metadata_for_target_side_hits(monkeypatch):
    """A hit in a target document must resolve its paired reference and variant."""
    from candyconc.services.backend import server as srv

    metadata = _MetadataMapping(
        {
            0: {"doc_id": "0", "model": "human", "path": "source.txt"},
            1: {"doc_id": "1", "ref_doc": "0", "model": "target", "path": "target.txt"},
        }
    )
    idx = SimpleNamespace(
        fast_index=SimpleNamespace(
            doc_metadata=metadata,
            doc_path_for_idx=lambda doc_id: f"doc-{doc_id}.txt",
        )
    )

    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: idx)
    monkeypatch.setattr(srv, "_paired_guard", lambda *_args: None)
    monkeypatch.setattr(srv, "_bounded_query_context", lambda value: value)
    monkeypatch.setattr(srv, "_tokenize_kw", lambda _keyword: ["rabbit"])
    monkeypatch.setattr(srv, "_doc_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_sentence_bounds_for_index", lambda _idx: [])
    monkeypatch.setattr(srv, "_doc_id_for_position", lambda *_args: 1)
    monkeypatch.setattr(srv, "_sentence_bounds_for_doc", lambda *_args, **_kwargs: [0])
    monkeypatch.setattr(srv, "_sentence_index_for_pos", lambda *_args: 0)
    monkeypatch.setattr(srv, "_sentence_data_for_indices", lambda *_args, **_kwargs: [{"index": 0}])
    monkeypatch.setattr(srv, "resolve_pair_groups", lambda *_args, **_kwargs: {0: [0, 1]})
    monkeypatch.setattr(srv, "_best_matching_sentence", lambda *_args, **_kwargs: ({"index": 0}, 1, 0.1, 0.9))
    monkeypatch.setattr(
        srv,
        "_kwic_from_sentence",
        lambda *_args, **_kwargs: {"left": "Der", "kw": "Hase", "right": "springt"},
    )

    async def run_inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(srv, "_run_heavy_scan", run_inline)

    result = asyncio.run(
        srv.analysis_kwic_parallel(
            {"corpus": "paired", "pos": 6, "keyword": "rabbit", "include_models": ["human"]}
        )
    )

    assert result["ref_doc"] == 0
    assert result["base_doc_id"] == 1
    assert result["variants"] == [
        {
            "doc_id": 0,
            "model": "human",
            "prompting_method": "",
            "text_type": "",
            "left": "Der",
            "kw": "Hase",
            "right": "springt",
            "matched": False,
            # Die Attrappe liefert einen Gegenstueck-Satz, also ausgerichtet.
            "aligned": True,
            "med": 1,
            "norm_med": 0.1,
            "similarity": 0.9,
        }
    ]
