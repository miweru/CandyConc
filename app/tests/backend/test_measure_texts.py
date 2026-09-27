"""Measure explanations, word-sketch glosses and corpus feature labels in both languages.

German stays the default rendering. With the request language ``en`` the
method card, the relation glosses and the feature labels come in English.
Word-sketch glosses follow the annotation scheme of the corpus, not the
interface language: TIGER ``cc`` is a comparative complement, ClearNLP ``cc``
a coordinating conjunction (erprobung B9).
"""

from __future__ import annotations

import json
from pathlib import Path

from candyconc.analysis_defaults import (
    METHOD_META,
    WORD_SKETCH_GLOSS_SCHEMES,
    build_method_block,
    word_sketch_relation_label,
)
from candyconc.domain.corpus import _corpus_feature_descriptor, dependency_label_scheme
from candyconc.i18n import LocalizedText, localize


def test_every_measure_explanation_exists_in_both_languages():
    for key, entry in METHOD_META.items():
        explanation = entry["explanation"]
        assert isinstance(explanation, LocalizedText), key
        assert explanation.en.strip() and explanation.en != explanation.de, key


def test_method_card_renders_in_the_request_language():
    block = build_method_block("keyness")
    german = localize(block, "de")
    english = localize(block, "en")
    lrc_de = next(s for s in german["statistics"] if s["key"] == "lrc")
    lrc_en = next(s for s in english["statistics"] if s["key"] == "lrc")
    assert lrc_de["name"] == "Konservatives Log Ratio (Evert 2022)"
    assert lrc_en["name"] == "Conservative Log Ratio (Evert 2022)"
    assert lrc_de["explanation"].startswith("Konservatives Log Ratio: die Grenze")
    assert lrc_en["explanation"].startswith("Conservative Log Ratio: the bound")
    assert "bound closer to zero" in lrc_en["latex_formula"]
    assert "nullnahe Grenze" in lrc_de["latex_formula"]
    diff = next(s for s in english["statistics"] if s["key"] == "diff_per_million")
    assert diff["name"] == "Difference per million"
    # The default (no request language) is the German text, as before.
    assert block["statistics"][0]["name"] == german["statistics"][0]["name"]


def test_contrast_override_and_frequency_formula_are_bilingual():
    contrast = localize(build_method_block("contrast"), "en")
    log_ratio = next(s for s in contrast["statistics"] if s["key"] == "log_ratio")
    assert log_ratio["name"] == "Log Ratio of the co-occurrence rates"
    assert log_ratio["smoothing"] == "+0.5 in both cells"
    frequency = localize(METHOD_META["frequency"], "en")
    assert "<mtext>occurrences</mtext>" in frequency["formula_mathml"]
    assert "Vorkommen" in METHOD_META["frequency"]["formula_mathml"]


def test_literature_references_follow_the_primary_sources():
    # methoden.md B11: Delta P is not Gries 2008 (the DP paper), STTR is not
    # Covington & McFall 2010 (MATTR), the LRC interval is not Hardie 2014.
    assert METHOD_META["delta_p_nc"]["reference"] == "Allan 1980; Ellis 2006; Gries 2013"
    assert METHOD_META["delta_p_cn"]["reference"] == "Allan 1980; Ellis 2006; Gries 2013"
    assert METHOD_META["sttr"]["reference"] == "Scott, WordSmith Tools"
    assert METHOD_META["mattr"]["reference"] == "Covington & McFall 2010"
    assert METHOD_META["lrc"]["reference"] == "Evert 2022; Clopper & Pearson 1934"
    assert "Hardie" not in METHOD_META["lrc"]["name"]


# --- word-sketch glosses ------------------------------------------------------


def test_cc_is_glossed_by_the_scheme_of_the_corpus():
    tiger = word_sketch_relation_label("cc", "tiger")
    clearnlp = word_sketch_relation_label("cc", "clearnlp")
    assert tiger == "Vergleichskomplement" and tiger.en == "comparative complement"
    assert clearnlp == "hat als koordinierende Konjunktion"
    assert clearnlp.en == "has coordinating conjunction"


def test_english_labels_get_english_scheme_glosses_in_both_languages():
    label = word_sketch_relation_label("amod_rev", "clearnlp")
    assert label == "adjektivischer Modifikator von"
    assert label.en == "adjectival modifier of"
    assert word_sketch_relation_label("dobj", "clearnlp").en == "has direct object"
    # A TIGER code in an English corpus has no ClearNLP meaning: raw code.
    assert word_sketch_relation_label("sb", "clearnlp") == "sb"
    # A ClearNLP code in a German corpus stays raw, too.
    assert word_sketch_relation_label("amod", "tiger") == "amod"


def test_unknown_scheme_and_unknown_labels_stay_raw():
    assert word_sketch_relation_label("cc", None) == "cc"
    assert word_sketch_relation_label("sb_rev", "ud") == "sb_rev"
    assert word_sketch_relation_label("totally_unknown", "clearnlp") == "totally_unknown"
    assert not isinstance(word_sketch_relation_label("cc", None), LocalizedText)


def test_tiger_glosses_keep_german_and_fix_the_direction_of_nk_rev():
    assert word_sketch_relation_label("sb_rev") == "Subjekt von"
    assert word_sketch_relation_label("sb_rev").en == "subject of"
    # nk_rev: the node is an NK element of the collocate (adjective of a
    # noun), it modifies the collocate. "modifiziert durch" had it backwards.
    assert word_sketch_relation_label("nk_rev", "tiger") == "Nomen-Kern-Element von"
    assert word_sketch_relation_label("sbp", "tiger").en == "has passivised subject (PP)"
    reverse = word_sketch_relation_label("pm_rev", "tiger")
    assert reverse == "morphologische Partikel (umgekehrte Richtung)"
    assert reverse.en == "morphological particle (reverse direction)"


def test_every_gloss_is_a_complete_pair():
    for scheme, table in WORD_SKETCH_GLOSS_SCHEMES.items():
        for code, gloss in table.items():
            assert isinstance(gloss, LocalizedText), (scheme, code)
            assert gloss.de.strip() and gloss.en.strip(), (scheme, code)


def _index(tmp_path: Path, name: str, build_meta: dict, source: str | None) -> Path:
    index_dir = tmp_path / name
    index_dir.mkdir()
    (index_dir / "index_build_meta.json").write_text(json.dumps(build_meta), "utf-8")
    if source is not None:
        (index_dir / "index_manifest.json").write_text(
            json.dumps({"manifest_version": 1, "annotation_source": source, "capabilities": {}}),
            "utf-8",
        )
    return index_dir


def test_dependency_label_scheme_comes_from_the_annotation_pipeline(tmp_path):
    assert dependency_label_scheme(_index(tmp_path, "de", {"spacy_model": "de_core_news_md"}, "spacy")) == "tiger"
    assert dependency_label_scheme(_index(tmp_path, "en", {"spacy_model": "en_core_web_sm"}, "spacy")) == "clearnlp"
    assert dependency_label_scheme(_index(tmp_path, "fr", {"spacy_model": "fr_core_news_sm"}, "spacy")) is None
    assert dependency_label_scheme(_index(tmp_path, "blank", {"spacy_model": "blank:en"}, "spacy")) is None
    gold = _index(
        tmp_path, "vrt", {"spacy_model": "de_core_news_md", "annotation_source": "gold_vrt"}, "native"
    )
    assert dependency_label_scheme(gold) is None
    assert dependency_label_scheme(tmp_path / "missing") is None


# --- corpus feature labels ----------------------------------------------------


def test_feature_labels_from_the_index_are_bilingual(tmp_path):
    caps = {"lemma_lex": True, "pos_lex": True, "morph_lex": True, "rel_lex": True}
    features = _corpus_feature_descriptor(caps, object(), tmp_path)
    english = localize(features, "en")
    german = localize(features, "de")
    labels_en = {a["id"]: a["label"] for a in english["token_attributes"]}
    labels_de = {a["id"]: a["label"] for a in german["token_attributes"]}
    assert labels_de["word"] == "Wortform" and labels_en["word"] == "Word form"
    assert labels_de["morph"] == "Morphologie" and labels_en["morph"] == "Morphology"
    assert labels_en["rel"] == "Dependency relation"
    groups_en = {g["id"]: g["label"] for g in english["frequency_groups"]}
    assert groups_en == {"word": "Word form", "lemma": "Lemma", "pos": "POS tag"}


# --- system panel and model connection -----------------------------------------


def test_system_cache_size_and_model_connection_profiles_are_bilingual():
    from candyconc.services.backend import model_route as modellweg
    from candyconc.services.backend.routes.system import _cache_size_text

    assert _cache_size_text(0) == "0 Einträge"
    assert localize(_cache_size_text(0), "en") == "0 entries"
    assert localize(_cache_size_text(1), "en") == "1 entry"
    profiles = localize(modellweg.stand()["profile"], "en")
    local = next(p for p in profiles if p["id"] == "lokal")
    assert local["name"] == "Local (LM Studio)"
    assert local["hinweis"] == "Runs on this device. No text leaves the computer."
    german = next(p for p in localize(modellweg.stand()["profile"], "de") if p["id"] == "lokal")
    assert german["hinweis"] == "Läuft auf diesem Gerät. Kein Text verlässt den Rechner."


# --- word sketch through the real route (English corpus) ------------------------


def test_word_sketch_route_glosses_an_english_corpus_with_clearnlp_labels():
    import os

    import pytest
    from fastapi.testclient import TestClient

    index = os.environ.get("CANDYCONC_INDEX_PATH")
    if not index or dependency_label_scheme(index) != "clearnlp":
        pytest.skip("CANDYCONC_INDEX_PATH is not an English spaCy index")
    from candyconc.services.backend.server import app

    client = TestClient(app)
    body = {"term": "freedom", "min_freq": 1}
    english = client.post("/api/v1/analysis/wordsketch", json=body, headers={"Accept-Language": "en, de;q=0.5"})
    german = client.post("/api/v1/analysis/wordsketch", json=body)
    assert english.status_code == german.status_code == 200, english.text
    labels_en = {r["relation"]: r["label"] for r in english.json()["relations"].values()}
    labels_de = {r["relation"]: r["label"] for r in german.json()["relations"].values()}
    assert labels_en, "no relation groups"
    for relation, label in labels_en.items():
        gloss = word_sketch_relation_label(relation, "clearnlp")
        assert label == localize(gloss, "en"), relation
        assert labels_de[relation] == localize(gloss, "de"), relation
    # No English relation gets a TIGER gloss such as "Vergleichskomplement".
    assert "Vergleichskomplement" not in labels_de.values()
    method_en = english.json()["method"]
    assert method_en["min_freq_semantics"].startswith("Partner rows with f >= min_freq")
