"""Evidence-package inventory and completeness statements match the visible content.

A metadata inventory must not consume the package before result items
are included. Exercise both configuration values so their effects remain
explicit."""

import pytest

from candyconc.candyconc_copilot import interpretation_synthesis as modul


def _inventar():
    return {
        "id": "E_metadata_values_1", "tool": "metadata_values", "query": "{}",
        "status": "success", "grounding_surface": ["status=success"],
        "fact_surface": {"ref_doc": [str(i) for i in range(20000)]},
    }


def _zaehlungen(n):
    return [
        {"id": f"E_query_count_{r}", "tool": "query_count",
         "query": f"daß im Teilkorpus {r}", "status": "success",
         "grounding_surface": [f"total={1000 + r}", f"per_million={10.5 + r}"]}
        for r in range(n)
    ]


def _im_paket(text, n):
    return sum(1 for r in range(n) if f"[E_query_count_{r}]" in text)


def _budget_des_piloten(monkeypatch):
    """Diese Proben rechnen im Budget, in dem der Fehler auftrat: 14.000 Zeichen.

    Seit dem 2026-09-26 ist die Grenze die Reissleine 300.000. Gegen sie waere jede Probe hier trivial erfuellt.
    """
    monkeypatch.setattr(modul, "PAKET_MAX_ZEICHEN", 14_000)


@pytest.fixture
def mit(monkeypatch):
    _budget_des_piloten(monkeypatch)
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")


@pytest.fixture
def ohne(monkeypatch):
    """Ausdruecklich aus: seit dem 2026-09-26 ist die Paketwahrheit Vorgabe."""
    _budget_des_piloten(monkeypatch)
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "0")


def test_ohne_schalter_frisst_das_inventar_das_paket(ohne):
    """So lief der Pilot. Die Haelfte, ohne die die Probe nichts pruefte."""
    text = modul.evidenz_paket_text([_inventar()] + _zaehlungen(105))
    assert _im_paket(text, 105) == 0


def test_mit_schalter_stehen_alle_ergebnisse_im_bestehenden_budget(mit):
    text = modul.evidenz_paket_text([_inventar()] + _zaehlungen(105))
    assert _im_paket(text, 105) == 105
    assert len(text) <= modul.PAKET_MAX_ZEICHEN + 400, (
        "Die Ergebnisse passen ins BESTEHENDE Budget. Kein Deckel wird angehoben."
    )


def test_mit_schalter_steht_das_inventar_hinten_und_gekuerzt(mit):
    text = modul.evidenz_paket_text([_inventar()] + _zaehlungen(3))
    assert text.index("[E_query_count_0]") < text.index("[E_metadata_values_1]")
    assert "Zeichen gekuerzt" in text


def test_mit_schalter_nennt_ein_gekuerztes_paket_die_fehlenden(mit, monkeypatch):
    monkeypatch.setattr(modul, "PAKET_MAX_ZEICHEN", 600)
    monkeypatch.setattr(modul, "paket_masse", lambda: (12, 600))
    text = modul.evidenz_paket_text(_zaehlungen(40))
    assert "EVIDENZ GEKÜRZT" in text
    assert "E_query_count_39" in text.split("EVIDENZ GEKÜRZT")[1], (
        "Wer gekuerzt wird, wird beim Namen genannt."
    )


def test_der_systemtext_behauptet_nur_ohne_schalter_vollstaendigkeit(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "0")
    alt, _ = modul.deutungs_synthese_messages("Frage?", "PAKET")
    assert "vollständig" in alt["content"]
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    neu, _ = modul.deutungs_synthese_messages("Frage?", "PAKET")
    assert "ist vollständig" not in neu["content"]
    assert "liegt vollständig vor" not in neu["content"]


# --------------------------------------------------------------------------
# Die knappe Darstellung (CANDYCONC_PAKET_KNAPP), gelesen am 2026-09-25 im
# Paket des ersten Versuchs: jedes create_docset stand doppelt darin, jedes
# query_count brauchte vierzehn Zeilen, und die Zaehlungen je Modell fielen
# hinten raus.
# --------------------------------------------------------------------------

def _zaehlung_ausfuehrlich(i):
    skalare = ["status=success", f"total={900 + i}", "query=daß",
               "query_mode=plain_word", "attribute=word", "case_insensitive=False",
               f"per_million={80.5 + i}", "corpus_tokens=142044149",
               f"denominator_tokens={11200783 + i}", "denominator_scope=docset",
               "denominator_source=corpus_index.docset_token_count",
               f"scope: corpus_id=ping, level=docset, docset_id=d{i}, doc_count=19272"]
    return {"id": f"E_query_count_{i}", "tool": "query_count", "status": "success",
            "query": f"daß in d{i}", "grounding_surface": skalare,
            "fact_surface": {"denominator_tokens": 11200783 + i, "per_million": 80.5 + i,
                             "query": "daß", "corpus_tokens": 142044149}}


def test_ohne_knapp_passen_die_zaehlungen_nicht(mit, monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "0")
    text = modul.evidenz_paket_text([_zaehlung_ausfuehrlich(i) for i in range(60)])
    assert _im_paket(text, 60) < 45


def test_knapp_passen_sie_und_die_ergebnisse_bleiben(mit, monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    text = modul.evidenz_paket_text([_zaehlung_ausfuehrlich(i) for i in range(60)])
    assert _im_paket(text, 60) == 60, "Knapp passen alle sechzig ins bestehende Budget."
    assert "total=959" in text and "per_million=139.5" in text, (
        "Die Ergebnisse selbst duerfen beim Verknappen nicht verloren gehen."
    )
    assert "denominator_source=" not in text, "Konstante Felder sind Wiederholung."


def test_knapp_behaelt_die_vorschau_bei_werkzeugen_ohne_belegflaeche(mit, monkeypatch):
    """collocate_stats kommt nur ueber die Vorschau an. Die darf nicht fallen."""
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    item = {"id": "E_collocate_stats_1", "tool": "collocate_stats", "status": "success",
            "query": "Volk", "grounding_surface": [],
            "payload_preview": '{"rows": [{"word": "deutsche", "f": 6306}]}'}
    assert "6306" in modul.evidenz_paket_text([item])


# Numeric deletion through CANDYCONC_ZAHLEN_STREICHEN is off by default.
# Check both settings explicitly.

def test_streichen_ist_aus_und_zuschaltbar(monkeypatch):
    monkeypatch.delenv("CANDYCONC_ZAHLEN_STREICHEN", raising=False)
    assert modul.zahlen_streichen_aktiv() is False
    monkeypatch.setenv("CANDYCONC_ZAHLEN_STREICHEN", "1")
    assert modul.zahlen_streichen_aktiv() is True
