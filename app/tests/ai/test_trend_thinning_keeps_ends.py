"""A reduced time series preserves both ends and reports the visible size.

Check that the evidence view retains the newest period as well as the
oldest, including after a second reduction for the model input."""

from __future__ import annotations

import pytest

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

# conftest installiert einen STUB fuer tool_wrappers. Ein direkter Import
# liefert ihn, nicht das Produkt.
_TW = _load_real_tool_wrappers()
_TREND_TOOL_MAX_PERIODS = _TW._TREND_TOOL_MAX_PERIODS
_cap_trend_periods = _TW._cap_trend_periods
from candyconc.analysis_defaults import gleichmaessige_auswahl  # noqa: E402


def reihe(von: int, bis: int) -> list[dict]:
    return [{"period": str(j), "hits": j - von} for j in range(von, bis + 1)]


# ------------------------------------------------------- die Auswahlpolitik


@pytest.mark.parametrize(
    "anzahl,deckel", [(73, 60), (73, 20), (754, 60), (100, 3), (5, 5), (2, 20), (1, 1)]
)
def test_beide_enden_bleiben(anzahl, deckel):
    idx = gleichmaessige_auswahl(anzahl, deckel)
    assert idx[0] == 0
    assert idx[-1] == anzahl - 1
    assert len(idx) <= max(deckel, 1)
    assert idx == sorted(set(idx)), "Indizes doppelt oder unsortiert"


def test_unter_dem_deckel_bleibt_alles():
    assert gleichmaessige_auswahl(10, 60) == list(range(10))


# --------------------------------------------------------- der erste Schnitt


def test_der_gemeldete_fall():
    """73 Jahre 1949 bis 2021. Vorher endete die Ausgabe bei 2008."""
    gekappt, gekuerzt = _cap_trend_periods(reihe(1949, 2021))
    assert gekuerzt is True
    assert len(gekappt) == _TREND_TOOL_MAX_PERIODS
    assert gekappt[0]["period"] == "1949"
    assert gekappt[-1]["period"] == "2021", (
        "Das Ende der Reihe fehlt. Genau danach fragt eine Trendfrage."
    )


def test_kurze_reihe_bleibt_unangetastet():
    voll = reihe(2000, 2020)
    gekappt, gekuerzt = _cap_trend_periods(voll)
    assert gekuerzt is False
    assert [z["period"] for z in gekappt] == [z["period"] for z in voll]


def test_werte_bleiben_unveraendert():
    """Ausduennen waehlt aus, es rechnet nicht um."""
    voll = reihe(1949, 2021)
    gekappt, _ = _cap_trend_periods(voll)
    nach_periode = {z["period"]: z["hits"] for z in voll}
    for z in gekappt:
        assert z["hits"] == nach_periode[z["period"]]


def test_chronologie_bleibt():
    gekappt, _ = _cap_trend_periods(reihe(1949, 2021))
    jahre = [int(z["period"]) for z in gekappt]
    assert jahre == sorted(jahre)


def test_undatiert_wird_nicht_ausgeduennt():
    """'undatiert' ist keine Periode der Reihe und faellt nie weg."""
    voll = reihe(1949, 2021) + [{"period": "undatiert", "hits": 7}]
    gekappt, _ = _cap_trend_periods(voll)
    assert gekappt[-1]["period"] == "undatiert"
    assert gekappt[-1]["hits"] == 7
    datiert = [z for z in gekappt if z["period"] != "undatiert"]
    assert datiert[0]["period"] == "1949" and datiert[-1]["period"] == "2021"


def test_monatsreihe_haelt_beide_enden():
    monate = [{"period": f"{1949 + i // 12}-{i % 12 + 1:02d}", "hits": i} for i in range(754)]
    gekappt, gekuerzt = _cap_trend_periods(monate)
    assert gekuerzt is True
    assert gekappt[0]["period"] == monate[0]["period"]
    assert gekappt[-1]["period"] == monate[-1]["period"]


# -------------------------------------------------------- der zweite Schnitt


def test_der_zweite_schnitt_duennt_auch_aus_und_beziffert():
    """Er bestimmt, was das Modell sieht, und war unbeziffert."""
    from candyconc.candyconc_copilot.grounding_evidence import (
        DEFAULT_GROUNDING_ROW_LIMIT,
        extract_raw_surface,
    )

    perioden = reihe(1949, 2021)
    flaeche = extract_raw_surface(
        {"periods": perioden}, bounded=True, werkzeug="trend_analysis"
    )
    sichtbar = flaeche["periods"]
    assert len(sichtbar) == DEFAULT_GROUNDING_ROW_LIMIT
    assert str(sichtbar[0]["period"]) == "1949"
    assert str(sichtbar[-1]["period"]) == "2021", (
        "Der Schnitt, der bestimmt was das Modell sieht, verliert das Ende."
    )
    assert flaeche["grounding_truncated"] is True
    assert flaeche["grounding_periods_total"] == 73
    assert flaeche["grounding_periods_visible"] == DEFAULT_GROUNDING_ROW_LIMIT


# ------------------------------------------------------------ der Warntext


def test_der_hinweis_nennt_was_da_ist():
    from candyconc.analysis_defaults import trend_kuerzungshinweis

    gekappt, _ = _cap_trend_periods(reihe(1949, 2021))
    text = trend_kuerzungshinweis(gekappt, 73)
    assert "60 von 73" in text
    assert "1949 bis 2021" in text
    assert "KEINE Summe über die Reihe" in text


def test_der_hinweis_nennt_keinen_ausweg_der_keiner_ist():
    """Der alte Text empfahl die Einstellung, die schon gewählt war.

    Er war wörtlich aus der 422-Meldung der REST-Route übernommen, wo der
    Überlauf typisch von Monatsgranularität kommt. Am 60er-Deckel stand er
    neben einem Aufrufer mit granularity='year', und die einzige Alternative
    war durch dieselbe 500er-Schranke gesperrt.
    """
    from candyconc.analysis_defaults import trend_kuerzungshinweis

    gekappt, _ = _cap_trend_periods(reihe(1949, 2021))
    text = trend_kuerzungshinweis(gekappt, 73)
    assert "granularity" not in text
    assert "docset_id" not in text


def test_der_hinweis_sagt_nicht_gekuerzt_wenn_nichts_da_ist():
    from candyconc.analysis_defaults import trend_kuerzungshinweis

    assert trend_kuerzungshinweis([], 0) == ""


def test_der_hinweis_nennt_die_letzte_DATIERTE_periode():
    from candyconc.analysis_defaults import trend_kuerzungshinweis

    voll = reihe(1949, 2021) + [{"period": "undatiert", "hits": 7}]
    gekappt, _ = _cap_trend_periods(voll)
    text = trend_kuerzungshinweis(gekappt, len(voll))
    assert "bis 2021" in text and "bis undatiert" not in text


# ------------------------------------------- beide Schnitte, EINE Politik


def test_undatiert_verdraengt_das_junge_ende_nicht():
    """Der Befund eines adversarialen Prüfers am 2026-08-30.

    Der erste Schnitt behandelte "undatiert" als Sonderfall und hängte ihn
    hinten an. Der zweite kannte den Sonderfall nicht, dünnte über die ganze
    Liste aus und hielt garantiert den LETZTEN Index — und der war jetzt
    "undatiert", nicht die jüngste datierte Periode. Das junge Ende ging also
    wieder verloren, genau der Defekt, gegen den der erste Schnitt gebaut war.
    """
    from candyconc.analysis_defaults import perioden_ausduennen

    voll = reihe(1949, 2021) + [{"period": "undatiert", "hits": 7}]
    erster = perioden_ausduennen(voll, 60)
    zweiter = perioden_ausduennen(erster, 20)
    for name, liste, deckel in (("erster", erster, 60), ("zweiter", zweiter, 20)):
        datiert = [z for z in liste if z["period"] != "undatiert"]
        assert len(liste) <= deckel, f"{name}: Deckel überschritten"
        assert datiert[0]["period"] == "1949", f"{name}: Anfang verloren"
        assert datiert[-1]["period"] == "2021", f"{name}: junges Ende verloren"
        assert any(z["period"] == "undatiert" for z in liste), f"{name}: Bucket verloren"


def test_mehrere_undatierte_buckets_stuerzen_nicht():
    from candyconc.analysis_defaults import perioden_ausduennen

    voll = reihe(1949, 2021) + [{"period": "undatiert", "hits": i} for i in range(3)]
    gekappt = perioden_ausduennen(voll, 20)
    datiert = [z for z in gekappt if z["period"] != "undatiert"]
    assert datiert[-1]["period"] == "2021"
    assert len(gekappt) <= 20


def test_nur_undatiert_stuerzt_nicht():
    from candyconc.analysis_defaults import perioden_ausduennen

    nur = [{"period": "undatiert", "hits": i} for i in range(30)]
    assert len(perioden_ausduennen(nur, 20)) == 30  # keine datierte Reihe zum Ausdünnen


def test_beide_schnitte_rufen_dieselbe_politik():
    """Zwei Politiken für zwei Schnitte war genau die Ursache."""
    import ast
    import pathlib

    wurzel = pathlib.Path(__file__).resolve().parents[2] / "src" / "candyconc"
    rufer = []
    for pfad in (
        wurzel / "candyconc_copilot" / "tool_wrappers.py",
        wurzel / "candyconc_copilot" / "grounding_evidence.py",
    ):
        baum = ast.parse(pfad.read_text(encoding="utf-8"))
        namen = {
            getattr(k.func, "id", None) or getattr(k.func, "attr", None)
            for k in ast.walk(baum)
            if isinstance(k, ast.Call)
        }
        rufer.append((pfad.name, "perioden_ausduennen" in namen))
    ohne = [n for n, hat in rufer if not hat]
    assert ohne == [], f"Diese Schnitte fahren eine eigene Politik: {ohne}"


def test_der_hinweis_ueberlebt_die_kuerzung_der_belegflaeche():
    """grounding_evidence kürzt jede Warnung auf 220 Zeichen.

    Abgeschnitten wurde bisher genau der Schlusssatz, also die einzige
    Aussage mit Warnwert.
    """
    from candyconc.analysis_defaults import trend_kuerzungshinweis

    gekappt, _ = _cap_trend_periods(reihe(1949, 2021))
    text = trend_kuerzungshinweis(gekappt, 73)
    assert len(text) <= 220, f"{len(text)} Zeichen, der Schluss wird abgeschnitten"
    assert "KEINE Summe über die Reihe" in text
