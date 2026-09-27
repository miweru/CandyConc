"""Synthesis receives version structure and keeps the submission separate from evidence."""

from types import SimpleNamespace

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_KONTEXT = {
    "corpus_id": "ping",
    "corpus_docs": 250535,
    "corpus_meta_fields": ["origin_id", "model", "register"],
    "corpus_meta_field_cardinality": {"origin_id": 19272, "model": 12, "register": 10},
}


def test_die_synthese_liest_die_zeile_quelltexte():
    korpus = modul.korpus_fuer_synthese(SimpleNamespace(ui_context=_KONTEXT))
    assert korpus.startswith("quelltexte: 19272 (13.0 Fassungen je Quelltext, Feld origin_id)")
    _system, nutzer = modul.deutungs_synthese_messages("F", "[E_1] keyness", korpus)
    assert "KORPUS:\nquelltexte: 19272" in nutzer["content"]
    assert nutzer["content"].index("KORPUS:") < nutzer["content"].index("EVIDENZ")


def test_ohne_karte_bleibt_die_nachricht_wie_sie_war():
    assert modul.korpus_fuer_synthese(SimpleNamespace(ui_context={})) == ""
    _system, nutzer = modul.deutungs_synthese_messages("F", "[E_1] keyness")
    assert "KORPUS" not in nutzer["content"]


def test_die_abgabe_steht_nicht_im_paket():
    abgabe = {"id": "E_deutung_abgeben_32", "tool": "deutung_abgeben", "status": "success",
              "query": '{"beantwortet": "Die Evidenz traegt die Stilfrage vollstaendig"}'}
    zaehlung = {"id": "E_query_count_21", "tool": "query_count", "status": "success", "query": "{}",
                "grounding_surface": ["total=2", "per_million=0.9"]}
    paket = modul.evidenz_paket_text([zaehlung, abgabe])
    assert "E_query_count_21" in paket
    assert "deutung_abgeben" not in paket and "vollstaendig" not in paket
