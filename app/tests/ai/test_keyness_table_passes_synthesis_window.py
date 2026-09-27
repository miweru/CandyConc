# -*- coding: utf-8 -*-
"""Keyness table facts survive the synthesis evidence window."""

from candyconc.candyconc_copilot.grounding_evidence import extract_raw_surface
from candyconc.candyconc_copilot.grounding_facts import (
    _metric_row_facts,
    select_balanced_observed_facts,
)
from candyconc.candyconc_copilot.grounding_schemas import (
    EvidenceItem,
    ObservedFact,
)

QUELLE = "E_keyness_5"


def _rohzeilen(anzahl: int) -> list:
    return [
        {
            "word": f"wort_{i:03d}",
            "target_freq": 1000 - i,
            "reference_freq": i + 1,
            "target_per_million": round(400 - i, 2),
            "log_ratio": round(9.9 - i * 0.07, 4),
        }
        for i in range(anzahl)
    ]


def _gekapptes_item() -> EvidenceItem:
    """Der Weg des Laufs: das Werkzeug rechnet 40 Zeilen. Bis zum 2026-09-25
    kappte die Modellsicht auf 20, seitdem sieht das Modell alle 40, und der
    Builder bekommt genau die Zeilen, die das Modell sah."""
    ausgabe = {
        "status": "success",
        "rows": _rohzeilen(40),
        "grounding_truncated": True,
    }
    roh = extract_raw_surface(ausgabe)
    assert len(roh["rows"]) == 40, len(roh["rows"])
    return EvidenceItem(
        id=QUELLE,
        tool="keyness",
        tool_call_id="call_5",
        query="{}",
        status="success",
        truncated=True,
        raw_surface={"rows": roh["rows"]},
        grounding_surface=["keyness: human gegen ai", "rank=1"],
    )


def _count_fakt(n: int) -> ObservedFact:
    return ObservedFact(
        id=f"{QUELLE}_count_{n}",
        statement=f"Die Seite traegt {1000 + n} Tokens.",
        fact_kind="count",
        source_evidence_ids=[QUELLE],
        supports_claims=["counts"],
    )


def _fremdquellen() -> list:
    fremde = []
    for i in range(45):
        fremde.append(ObservedFact(
            id=f"E_fremd_{i}_count",
            statement=f"Fremdquelle {i}: {i} Treffer.",
            fact_kind="count",
            source_evidence_ids=[f"E_fremd_{i}"],
            supports_claims=["counts"],
        ))
    return fremde


def test_die_ganze_gesehene_tabelle_erreicht_die_verifikation():
    fakten = _metric_row_facts(_gekapptes_item())
    serien = [f for f in fakten if f.id.endswith("_tabellen_serie")]
    assert serien, "Der Tabellen-Traeger wurde bei 20 Zeilen nicht gebaut."
    # Die Konkurrenz um die 64 Plaetze, wie im Lauf: zwei counts der
    # selben Quelle und 45 Fremdquellen.
    fakten.extend([_count_fakt(1), _count_fakt(2)])
    fakten.extend(_fremdquellen())
    assert len(fakten) > 64
    fenster = select_balanced_observed_facts(fakten, max_items=64)
    im_fenster = [f for f in fenster if f.id.endswith("_tabellen_serie")]
    assert im_fenster, (
        "Die Tabelle erreichte das Synthesefenster nicht — wieder nur "
        "row[1] und row[2]."
    )
    traf = im_fenster[0].statement
    assert "wort_000" in traf and "wort_039" in traf, traf[:300]
    # Nichts ueberfaehrt das Fenster: der Traeger verdraengt keine
    # Fremdquelle ganz (source coverage bleibt erhalten).
    fremde_im_fenster = {
        f.source_evidence_ids[0] for f in fenster
        if f.source_evidence_ids and f.source_evidence_ids[0].startswith("E_fremd")
    }
    assert len(fremde_im_fenster) >= 40, len(fremde_im_fenster)


def test_ohne_konkurrenz_reiten_die_zeilen_einzeln_mit():
    """Kontrolle: eine kleine Quelle ohne Fensterdruck zeigt weiter jede
    Zeile einzeln — der Traeger ersetzt nichts, er begleitet nur."""
    fakten = _metric_row_facts(_gekapptes_item())
    fenster = select_balanced_observed_facts(fakten, max_items=64)
    zeilen = [f for f in fenster if f.fact_kind == "ranked_row"]
    assert len(zeilen) == 40, len(zeilen)
