"""Regression test (FT id 10): wordsketch relation codes carry German glosses.

``word_sketch_relation_label`` maps the raw TIGER/German-dependency codes the
word-sketch path emits (sb_rev, oa_rev, nk, ag_rev, ...) to human-readable
German labels, reflecting the ``_rev`` reversed-direction suffix. Unknown codes
degrade to the raw code (never raise).
"""

from __future__ import annotations

from candyconc.analysis_defaults import word_sketch_relation_label


def test_known_relations_have_german_labels():
    assert word_sketch_relation_label("sb_rev") == "Subjekt von"
    assert word_sketch_relation_label("oa_rev") == "Akkusativobjekt von"
    assert "Genitivattribut" in word_sketch_relation_label("ag_rev")
    assert "Nomen-Kern" in word_sketch_relation_label("nk")


def test_rev_suffix_falls_back_to_base_with_direction_note():
    # A synthetic code whose BASE is known but whose _rev form is not explicitly
    # listed resolves via the base gloss + a reversed-direction note. We patch in
    # a base-only entry to exercise the fallback branch deterministically.
    from candyconc import analysis_defaults as ad

    ad._WORD_SKETCH_RELATION_GLOSSES.setdefault("xq", "Test-Relation")
    try:
        label = word_sketch_relation_label("xq_rev")
        assert "Test-Relation" in label
        assert "umgekehrte Richtung" in label
    finally:
        ad._WORD_SKETCH_RELATION_GLOSSES.pop("xq", None)


def test_unknown_relation_returns_raw_code():
    assert word_sketch_relation_label("totally_unknown_code") == "totally_unknown_code"
    assert word_sketch_relation_label("") == ""
