"""Preserve a line break immediately adjacent to the hit in the evidence package."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_CLAUDE = "deplain_apa_doc:deplain_apa_0372::claude_opus_4_7_generator::claude-opus-4-7::1::53af38424b041e5f"


def _item(*reihen: dict) -> dict:
    return {"fact_surface": {"rows": list(reihen), "total": len(reihen)}}


def _zeile(links: str, rechts: str, kw: str = "Das", match: str = "Das heißt", pos: int = 2919263) -> dict:
    return {"kw": kw, "left": links, "right": rechts, "file": _CLAUDE, "match": match, "pos": pos}


def test_der_umbruch_vor_dem_treffer_bleibt_sichtbar():
    zeilen = modul._knapp_treffer(
        _item(_zeile("lang an der Macht . \n", "heißt : Er hat sehr lange das")), ["kwic[0] x"])
    assert zeilen == [
        "Treffer 0: lang an der Macht . \\n [Das heißt] : Er hat sehr lange das"
        f"  ({_CLAUDE}, pos 2919263)"
    ]


def test_der_umbruch_direkt_hinter_dem_treffer_bleibt_sichtbar():
    # Mehrworttreffer: die Worte des Treffers fallen rechts weg, der Umbruch dahinter nicht.
    mehrwort = modul._knapp_treffer(_item(_zeile("frei .", "heißt \n Man muss nichts")), ["kwic[0] x"])
    assert mehrwort[0].startswith("Treffer 0: frei . [Das heißt] \\n Man muss nichts  (")
    # Eintokentreffer: der rechte Kontext beginnt selbst mit dem Umbruch.
    eintoken = modul._knapp_treffer(
        _item(_zeile("Familien-Tragödie . Das", "\n In einer Familie", kw="bedeutet", match="")),
        ["kwic[0] x"])
    assert eintoken[0].startswith("Treffer 0: Familien-Tragödie . Das [bedeutet] \\n In einer Familie  (")


def test_zeilen_ohne_umbruch_am_rand_bleiben_wie_sie_waren():
    zeilen = modul._knapp_treffer(
        _item(_zeile("Daten sollen verändert worden sein .", "heißt : \n Sie sollen gefälscht")),
        ["kwic[0] x"])
    assert zeilen[0].startswith(
        "Treffer 0: Daten sollen verändert worden sein . [Das heißt] : \\n Sie sollen gefälscht  (")


def test_die_zitatsuche_liest_den_umbruch_weiter_als_leerraum():
    # _zitat_heuhaufen ruft mit umbruch=" ": ein Zitat über den Umbruch hinweg bleibt belegt.
    zeilen = modul._knapp_treffer(
        _item(_zeile("lang an der Macht . \n", "heißt : Er hat sehr lange das")), ["kwic[0] x"], umbruch=" ")
    assert zeilen[0].startswith("Treffer 0: lang an der Macht . [Das heißt] : Er hat sehr lange das  (")
