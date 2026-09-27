# -*- coding: utf-8 -*-
"""A refusal contradicted by its own evidence is rejected."""

from candyconc.candyconc_copilot.grounding_schemas import ObservedFact
from candyconc.candyconc_copilot.grounding_verifier import _widerlegte_absagen


class _Claim:
    def __init__(self, id, text, fact_ids, kind="interpretation"):
        self.id = id
        self.text = text
        self.fact_ids = fact_ids
        self.claim_kind = kind


class _Envelope:
    def __init__(self, claims):
        self.claims = claims


def _fakt(id, kind, statement):
    return ObservedFact(
        id=id,
        statement=statement,
        fact_kind=kind,
        source_evidence_ids=["E_quelle"],
        exactness="exact",
    )


def test_absage_mit_positiven_belegen_ist_widerlegt(monkeypatch):
    monkeypatch.setenv("CANDYCONC_ABSAGEN_DURCHSETZUNG", "1")
    envelope = _Envelope([
        _Claim(
            "C_absage",
            "Die Evidenz liefert keine Wortfrequenzen oder Tokenraten.",
            ["E1"],
        ),
    ])
    fakten = [
        _fakt("E1", "count", "query_count zaehlt 551103 Treffer fuer dass."),
    ]
    assert _widerlegte_absagen(envelope, fakten) == ["C_absage"]


def test_ehrliche_leere_bleibt_stehen(monkeypatch):
    """Die Absage ruht auf einem negative_result-Fakt — sie ist wahr und
    bleibt unangetastet. Bei eingeschalteter Durchsetzung geprueft."""
    envelope = _Envelope([
        _Claim(
            "C_ehrlich",
            "Die Evidenz liefert keine Lesbarkeitsmasse wie Satzlänge.",
            ["E2"],
        ),
    ])
    fakten = [
        _fakt(
            "E2",
            "negative_result",
            "Keine Messstelle fuer Lesbarkeitsmasse im Lauf.",
        ),
    ]
    import os
    os.environ["CANDYCONC_ABSAGEN_DURCHSETZUNG"] = "1"
    try:
        assert _widerlegte_absagen(envelope, fakten) == []
    finally:
        os.environ.pop("CANDYCONC_ABSAGEN_DURCHSETZUNG", None)


def test_absage_ohne_belege_wird_nicht_beurteilt(monkeypatch):
    """Ohne fact_ids fehlt der Massstab: die Durchsetzung urteilt nicht
    ueber eine Absage, die nichts Zitierbares traegt."""
    monkeypatch.setenv("CANDYCONC_ABSAGEN_DURCHSETZUNG", "1")
    envelope = _Envelope([
        _Claim("C_offen", "Es fehlen Vergleiche zu anderen Sprachen.", []),
    ])
    assert _widerlegte_absagen(envelope, [_fakt("E9", "count", "9 Treffer")]) == []


def test_nur_der_widerlegte_claim_faellt(monkeypatch):
    monkeypatch.setenv("CANDYCONC_ABSAGEN_DURCHSETZUNG", "1")
    envelope = _Envelope([
        _Claim(
            "C_absage",
            "Die Evidenz liefert keine Wortfrequenzen oder Tokenraten.",
            ["E1"],
        ),
        _Claim(
            "C_andere",
            "Die Evidenz zeigt keine Verteilung ueber Register.",
            ["E2"],
        ),
    ])
    fakten = [
        _fakt("E1", "count", "query_count zaehlt 551103 Treffer."),
        _fakt("E2", "negative_result", "Keine Registeraufschluesselung."),
    ]
    assert _widerlegte_absagen(envelope, fakten) == ["C_absage"]


def test_der_schalter_ist_fuer_die_isolation_da(monkeypatch):
    """Der Messarm der sauberen Isolation laeuft mit abgeschalteter
    Durchsetzung, sonst byte-gleich zum Durchsetzung-Arm."""
    monkeypatch.setenv("CANDYCONC_ABSAGEN_DURCHSETZUNG", "0")
    envelope = _Envelope([
        _Claim(
            "C_absage",
            "Die Evidenz liefert keine Wortfrequenzen oder Tokenraten.",
            ["E1"],
        ),
    ])
    fakten = [
        _fakt("E1", "count", "query_count zaehlt 551103 Treffer fuer dass."),
    ]
    assert _widerlegte_absagen(envelope, fakten) == []
    monkeypatch.setenv("CANDYCONC_ABSAGEN_DURCHSETZUNG", "1")
    assert _widerlegte_absagen(envelope, fakten) == ["C_absage"]
