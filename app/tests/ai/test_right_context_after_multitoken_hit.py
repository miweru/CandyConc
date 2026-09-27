"""Right context extends ctx tokens beyond the end of a multi-token hit."""

from tests.ai.test_tool_wrappers_parity_r5 import _TW
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_KETTE = '[word="ich"] []{3,6} [word="nicht"]'


def _zeilen(ctx: int) -> list:
    antwort = _TW.run_cqlf_query_tool(_KETTE, ctx=ctx, limit=10, sort_by="position")
    return [z for z in antwort["rows"] if len(z.get("match_tokens") or []) > ctx]


def test_hinter_dem_treffer_stehen_ctx_token(active_index):  # noqa: F811
    zeilen = _zeilen(2)
    assert zeilen, "Positive Klasse fehlt: kein Treffer laenger als ctx"
    for zeile in zeilen:
        # Ein Zeilenumbruch belegt eine Indexposition und steht in match_tokens als
        # eigenes Token, in right als Leerraum. Verglichen werden die Woerter.
        fortsetzung = " ".join(zeile["match_tokens"][1:]).split()
        rechts = zeile["right"].split()
        assert rechts[: len(fortsetzung)] == fortsetzung, zeile
        assert 0 < len(rechts) - len(fortsetzung) <= 2, zeile


def test_left_bleibt_wie_bestellt(active_index):  # noqa: F811
    for zeile in _zeilen(2):
        assert len(zeile["left"].split()) <= 2, zeile


def test_das_paket_zeigt_den_folgetext(active_index):  # noqa: F811
    from candyconc.candyconc_copilot.interpretation_synthesis import _knapp_treffer

    zeile = _zeilen(2)[0]
    item = {"fact_surface": {"rows": [zeile], "total": 1}}
    [text] = _knapp_treffer(item, [])
    danach = " ".join(zeile["right"].split()[len(" ".join(zeile["match_tokens"][1:]).split()):])
    assert danach and f"] {danach}" in text, text
