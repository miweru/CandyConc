"""P1 (Runde 2): der Serien-Fakt traegt die volle Zeitachse durch die Kappe.

Messung 35/diachronie-1: 366 belegte Fakten, 302 erreichen die Synthese
nicht — die Endfassung endete bei 1961, obwohl die Interim-Antwort den
Bruch 1999-2001 bereits datiert hatte. Ursache: ein Trend-Turn erzeugt
einen Fakt je Periode; die 64er-Kappe mit Prioritaet-Spread zerschneidet
die Zeitachse. Der Serien-Fakt (ein Fakt mit dem kompakten Verlauf) muss
die Kappe ueberleben.
"""

from candyconc.candyconc_copilot.grounding_schemas import EvidenceItem
from candyconc.candyconc_copilot.grounding_facts import (
    _trend_facts,
    select_synthesis_window,
)


def _trend_item(perioden: int = 73) -> EvidenceItem:
    raw = {
        "periods": [
            {
                "period": str(1949 + i),
                "documents": 1000 + i,
                "hits": i * 7,
                "tokens": 500000 + i * 1000,
                "per_million": round(i * 1.5 + (i * 13) % 11, 1),
            }
            for i in range(perioden)
        ]
    }
    return EvidenceItem(
        id="E_trend_1",
        tool="trend_analysis",
        tool_call_id="call_1",
        query="{}",
        status="success",
        truncated=False,
        raw_surface=raw,
        grounding_surface=[
            "trend: 'Freiheit' je Jahr, Feld protocol_date, granularity year",
            "periods_total=73, zurueckgegeben=60 (gekuerzt)",
        ],
    )


def test_serien_fakt_ueberlebt_die_synthese_kappe():
    item = _trend_item(73)
    fakten = _trend_facts(item)
    # 73 Perioden-Fakten plus 1 Serien-Fakt; die Kappe behaelt nur einen Teil.
    assert len(fakten) == 74
    fenster = select_synthesis_window(fakten, analysis_family="analysis_report")
    assert len(fenster) < len(fakten)
    verlauf = [
        f for f in fenster
        if "1949:" in f.statement and "2021:" in f.statement
    ]
    assert verlauf, (
        "Kein Fakt im Synthesefenster traegt den kompakten Verlauf mit "
        "erster und letzter Periode — die Zeitachse wurde wieder gekappt."
    )


def test_kurze_serie_bekommt_keinen_zusaetzlichen_serien_fakt():
    item = _trend_item(12)
    fakten = _trend_facts(item)
    assert len(fakten) == 12
    assert all("1949:" not in f.statement or "1960:" not in f.statement
               for f in fakten)


def _keyness_item(zeilen: int = 120) -> EvidenceItem:
    rows = [
        {
            "word": f"wort_{i:03d}",
            "target_freq": 1000 - i,
            "reference_freq": i + 1,
            "log_ratio": round(9.9 - i * 0.07, 4),
        }
        for i in range(zeilen)
    ]
    return EvidenceItem(
        id="E_keyness_1",
        tool="keyness",
        tool_call_id="call_2",
        query="{}",
        status="success",
        truncated=False,
        raw_surface={"rows": rows},
        grounding_surface=["keyness: ai_pooled gegen human_ref", "rank=1"],
    )


def test_ranked_tabelle_serie_ueberlebt_die_synthese_kappe():
    item = _keyness_item(120)
    fakten = []
    from candyconc.candyconc_copilot.grounding_facts import _metric_row_facts
    fakten.extend(_metric_row_facts(item))
    assert len(fakten) == 121  # 120 Zeilen-Fakten + 1 Tabellen-Serie
    fenster = select_synthesis_window(fakten, analysis_family="analysis_report")
    assert len(fenster) < len(fakten)
    serie = [f for f in fenster if f.id.endswith("_tabellen_serie")]
    assert serie, "Die kompakte Rangliste hat die Kappe nicht ueberlebt."
    assert "wort_000" in serie[0].statement and "wort_047" in serie[0].statement


def test_keyness_nenner_fakt_wird_erzeugt_und_ueberlebt():
    from candyconc.candyconc_copilot.grounding_facts import (
        _keyness_nenner_fakt,
    )
    item = EvidenceItem(
        id="E_key_9",
        tool="keyness",
        tool_call_id="call_9",
        query="{}",
        status="success",
        truncated=False,
        raw_surface={
            "rows": [{"word": "man", "target_freq": 100, "reference_freq": 1}],
            "diagnostics": {
                "target_tokens": 2333065,
                "target_tokens_roh": 3330650,
                "reference_tokens": 225445,
                "reference_tokens_roh": 254450,
            },
        },
        grounding_surface=[
            "keyness: ai_pooled gegen human_ref",
            "target_tokens=2333065; reference_tokens=225445 (POS-gefiltert)",
        ],
    )
    fakten = _keyness_nenner_fakt(item)
    assert len(fakten) == 1
    assert "2333065" in fakten[0].statement
    assert "225445" in fakten[0].statement
