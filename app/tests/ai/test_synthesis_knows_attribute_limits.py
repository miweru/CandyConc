"""Synthesis receives the available corpus attributes and their limitations."""

from types import SimpleNamespace

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_PING = {
    "corpus_id": "ping",
    "corpus_docs": 250535,
    "corpus_meta_fields": ["origin_id", "model", "register"],
    "corpus_meta_field_cardinality": {"origin_id": 19272, "model": 12, "register": 10},
    "corpus_attributes": ["word", "lemma"],
    "corpus_lemma_ist_wortform": True,
    "corpus_constant_attributes": ["pos", "morph"],
}


def _korpus(kontext):
    return modul.korpus_fuer_synthese(SimpleNamespace(ui_context=kontext))


def test_die_synthese_liest_die_einwertigen_attribute():
    korpus = _korpus(_PING)
    assert "einwertige attribute: pos, morph" in korpus
    assert "auch nicht in CQL" in korpus


def test_die_synthese_liest_die_attribute_und_das_lemma():
    korpus = _korpus(_PING)
    assert "attribute: word, lemma" in korpus
    assert "lemma: kleingeschriebene Wortform, nicht lemmatisiert" in korpus


def test_die_zeile_quelltexte_bleibt_vorn():
    assert _korpus(_PING).startswith("quelltexte: 19272")


def test_ohne_attributangaben_keine_attributzeilen():
    kontext = {k: v for k, v in _PING.items() if not k.startswith(("corpus_attributes", "corpus_lemma", "corpus_constant"))}
    korpus = _korpus(kontext)
    assert "attribute" not in korpus and "lemma:" not in korpus
