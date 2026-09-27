"""The evidence appendix includes the rows cited by the answer."""

from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
from candyconc.candyconc_copilot.recipe_runtime import politur_mit_zitatwache

_WOERTER = ["Bragança", "Habsburgo", "B.=(\\z", "queso", "leche", "Lorena", "Fazit"]


def _posten(eid, werkzeug, reihen):
    return make_evidence_item(item_id=eid, tool=werkzeug, tool_call_id=eid, query="{}",
                              output={"status": "success", "rows": reihen},
                              analysis_family="").to_dict()


def _keyness():
    return _posten("E_keyness_4", "keyness", [
        {"word": w, "direction": "target", "target_freq": 3000 - i, "reference_freq": i, "ll": 500.0 - i}
        for i, w in enumerate(_WOERTER)])


def _belegzeile(text, eid):
    return next(z for z in text.split("\n") if z.startswith(f"- [{eid}]"))


def test_die_gedruckte_zeile_steht_im_anhang():
    text = ("KI-Fassungen schreiben „Fazit“ häufiger (114,8 zu 13,6 pro Million) [[beleg:E_keyness_4]].\n\n"
            "Artefakte sind „Bragança“ und „queso“ [[beleg:E_keyness_4]].")
    poliert, _ = politur_mit_zitatwache(text, [_keyness()], eigene_zitate_bleiben=True)
    zeile = _belegzeile(poliert, "E_keyness_4")
    assert "rows[6]" in zeile and "rows[3]" in zeile, zeile
    assert zeile.index("rows[6]") < zeile.index("rows[0]") < zeile.index("rows[3]"), zeile
    assert "rows[1]" not in zeile, zeile


def test_der_zitierte_kwic_beleg_steht_im_anhang():
    reihen = [{"kw": "Fazit", "left": f"Absatz {i} . * *", "right": f": Titel {i} mit Rest"} for i in range(6)]
    reihen[4] = {"kw": "Fazit", "left": "entsprechende Technik . \n\n * *", "right": ": Ein Weckruf mit offenen Fragen"}
    text = "Oft als Überschrift, etwa „* * [Fazit]: Ein Weckruf...“ [[beleg:E_run_cqlf_query_6]]."
    poliert, _ = politur_mit_zitatwache(
        text, [_posten("E_run_cqlf_query_6", "run_cqlf_query", reihen)], eigene_zitate_bleiben=True)
    zeile = _belegzeile(poliert, "E_run_cqlf_query_6")
    assert "Ein Weckruf" in zeile, zeile
    assert zeile.index("kwic[4]") < zeile.index("kwic[0]"), zeile


def test_ohne_zitierte_zeile_bleibt_die_reihenfolge():
    poliert, _ = politur_mit_zitatwache("Ein Befund [[beleg:E_keyness_4]].", [_keyness()],
                                        eigene_zitate_bleiben=True)
    zeile = _belegzeile(poliert, "E_keyness_4")
    assert zeile.index("rows[0]") < zeile.index("rows[1]") < zeile.index("rows[2]"), zeile
