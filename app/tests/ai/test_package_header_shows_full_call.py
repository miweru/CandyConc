"""Each evidence-package header shows the complete call and its subcorpus."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul

KENNUNG = "253413b7da0c479b8d618e8f79c369ad"
ABFRAGE = '[word="nicht"%c] [word="nur"] []{0,8} [word="sondern"] [word="auch"]'


def _teilkorpus():
    return {
        "id": "E_create_docset_8", "tool": "create_docset",
        "query": '{"filters": {"model": "gemini-3.5-flash"}, "label": "mod_gemini-3.5-flash"}',
        "status": "success",
        "grounding_surface": [f"docset_id={KENNUNG}",
                              "label=mod_gemini-3.5-flash  doc_count=19272  token_count=7141534"],
        "fact_surface": {"docset_id": KENNUNG, "label": "mod_gemini-3.5-flash",
                         "doc_count": 19272, "token_count": 7141534},
    }


def _zaehlung():
    import json
    return {
        "id": "E_query_count_31", "tool": "query_count",
        "query": json.dumps({"docset_id": KENNUNG, "query": ABFRAGE}),
        "status": "success",
        "grounding_surface": ["total=499", "per_million=69.9"],
        "fact_surface": {"total": 499, "per_million": 69.9,
                         "scope": {"level": "docset", "docset_id": KENNUNG}},
    }


def _kopf(text, kennung):
    return next(z for z in text.splitlines() if z.startswith(f"[{kennung}]"))


def test_der_kopf_zeigt_die_ganze_abfrage(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    kopf = _kopf(modul.evidenz_paket_text([_teilkorpus(), _zaehlung()]), "E_query_count_31")
    assert '[word=\\"auch\\"]' in kopf


def test_der_kopf_nennt_das_teilkorpus(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    kopf = _kopf(modul.evidenz_paket_text([_teilkorpus(), _zaehlung()]), "E_query_count_31")
    assert "mod_gemini-3.5-flash" in kopf


def test_ohne_create_docset_bleibt_die_kennung(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    kopf = _kopf(modul.evidenz_paket_text([_zaehlung()]), "E_query_count_31")
    assert KENNUNG in kopf and "Teilkorpus" not in kopf


def test_lange_listen_stehen_als_anzahl_da(monkeypatch):
    import json
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    teil = {
        "id": "E_create_docset_1", "tool": "create_docset",
        "query": json.dumps({"doc_ids": list(range(5000)), "label": "auswahl"}),
        "status": "success", "grounding_surface": ["docset_id=x"],
    }
    kopf = _kopf(modul.evidenz_paket_text([teil]), "E_create_docset_1")
    assert "5000 Werte" in kopf and '"label": "auswahl"' in kopf
    assert len(kopf) < 300
