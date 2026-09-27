"""STEP 9 (full): embedding-backed alignment cost path in _align_sentence_lists.

Track A delivered the additive scaffolding (method dispatch + not_applicable when
sentence embeddings are absent). This proves the actual embed/hybrid COST path:
with injected synthetic sentence vectors (keyed by SentenceData.start_pos), the
Needleman-Wunsch alignment uses cosine distance instead of token edit distance,
while method='edit' stays byte-identical to the default. No real re-ingest needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.services.backend import server as srv  # noqa: E402
from candyconc.services.backend.server import SentenceData  # noqa: E402


def _sent(index, start, text):
    toks = text.split()
    return SentenceData(index=index, start_pos=start, end_pos=start + len(toks), text=text, tokens=toks)


def _ref_var():
    # ref0/var0 are lexically identical; ref1/var1 differ lexically ("c d" vs "x y").
    ref = [_sent(0, 0, "a b"), _sent(1, 10, "c d")]
    var = [_sent(0, 100, "a b"), _sent(1, 110, "x y")]
    return ref, var


def test_edit_default_is_byte_identical():
    ref, var = _ref_var()
    pairs_default, summary_default = srv._align_sentence_lists(ref, var)
    pairs_edit, summary_edit = srv._align_sentence_lists(ref, var, method="edit")
    assert pairs_default == pairs_edit
    assert summary_default == summary_edit
    assert summary_default.get("status") != "not_applicable"


def test_embed_without_vectors_is_not_applicable():
    ref, var = _ref_var()
    # No idx, no injected vectors → embeddings unavailable → graceful envelope.
    pairs, summary = srv._align_sentence_lists(ref, var, method="embed")
    assert pairs == []
    assert summary["status"] == "not_applicable"
    assert summary["reason"] == "sentence_embeddings_unavailable"


def test_embed_with_injected_vectors_uses_cosine():
    ref, var = _ref_var()
    # Vectors keyed by start_pos. ref1 (start 10) is made cosine-close to var1
    # (start 110) even though they are lexically different — embed alignment should
    # still pair them via the semantic cost.
    vecs = {
        0: [1.0, 0.0],     # ref0 "a b"
        10: [0.0, 1.0],    # ref1 "c d"
        100: [1.0, 0.0],   # var0 "a b"  (== ref0)
        110: [0.0, 1.0],   # var1 "x y"  (cosine-identical to ref1 despite lexical diff)
    }
    pairs, summary = srv._align_sentence_lists(ref, var, method="embed", sentence_vectors=vecs)
    assert summary.get("status") != "not_applicable"
    assert summary["aligned_pairs"] >= 1
    # diagonal pairs (ref0~var0, ref1~var1) should be aligned with high similarity
    aligned = [p for p in pairs if p.get("ref_index") is not None and p.get("var_index") is not None]
    assert aligned
    assert any(float(p.get("similarity") or 0.0) > 0.9 for p in aligned)


def test_hybrid_blends_edit_and_embed():
    ref, var = _ref_var()
    vecs = {0: [1.0, 0.0], 10: [0.0, 1.0], 100: [1.0, 0.0], 110: [0.0, 1.0]}
    pairs, summary = srv._align_sentence_lists(ref, var, method="hybrid", sentence_vectors=vecs)
    assert summary.get("status") != "not_applicable"
    assert summary["aligned_pairs"] >= 1


def test_unknown_method_rejected():
    ref, var = _ref_var()
    with pytest.raises(Exception):
        srv._align_sentence_lists(ref, var, method="bogus")


def test_embed_pair_cost_helper():
    vm = {1: [1.0, 0.0], 2: [1.0, 0.0], 3: [0.0, 1.0], 4: [0.0, 0.0]}
    # identical vectors → cost 0, sim 1
    cost, sim, ok = srv._embed_pair_cost(vm, 1, 2)
    assert ok and abs(cost) < 1e-9 and abs(sim - 1.0) < 1e-9
    # orthogonal → cost 0.5, sim 0.5
    cost, sim, ok = srv._embed_pair_cost(vm, 1, 3)
    assert ok and abs(cost - 0.5) < 1e-9 and abs(sim - 0.5) < 1e-9
    # missing key / zero-norm → ok False (caller falls back to edit)
    assert srv._embed_pair_cost(vm, 1, 99)[2] is False
    assert srv._embed_pair_cost(vm, 1, 4)[2] is False
