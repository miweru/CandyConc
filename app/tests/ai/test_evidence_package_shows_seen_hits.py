"""The evidence package shows the KWIC hits seen by the model, one per line."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul


def _kwic_element(gesehen=20, erhoben=50):
    reihen = [{"kw": "nicht", "left": f"links {i}", "right": f"nur X{i} , sondern auch rechts {i}",
               "file": f"quelle_{i}::gpt-5.5", "match": f"nicht nur X{i} , sondern auch", "pos": 1000 + i}
              for i in range(erhoben)]
    flaeche = []
    for i in range(gesehen):
        flaeche += [f'match[{i}]="nicht nur X{i} , sondern auch"', f"rows[{i}] {{...}}", f'kwic[{i}] "links {i} nicht ..."']
    return {"id": "E_run_cqlf_query_7", "tool": "run_cqlf_query", "query": "{}", "status": "success",
            "grounding_surface": flaeche + ["total=45599", "metric[0] kw=nicht"],
            "fact_surface": {"total": 45599, "rows": reihen}}


def test_alle_gesehenen_treffer_mit_quelle_und_der_rest_benannt(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    paket = modul.evidenz_paket_text([_kwic_element()])
    zeilen = [z.strip() for z in paket.splitlines()]
    treffer = [z for z in zeilen if z.startswith("Treffer ")]
    assert len(treffer) == 20, "So viele Treffer, wie das Modell sah."
    assert treffer[0] == "Treffer 0: links 0 [nicht nur X0 , sondern auch] rechts 0  (quelle_0::gpt-5.5, pos 1000)"
    assert any("30 weitere Treffer" in z and "total=45599" in z for z in zeilen)
    assert not any(z.startswith(("match[", "kwic[", "rows[")) for z in zeilen)
    assert "metric[0]" not in paket


def test_element_ohne_trefferzeilen_bleibt_wie_es_war(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    zaehlung = {"id": "E_query_count_2", "tool": "query_count", "query": "{}", "status": "success",
                "grounding_surface": ["total=551103", "per_million=3879.8"],
                "fact_surface": {"total": 551103}}
    paket = modul.evidenz_paket_text([zaehlung])
    assert "total=551103" in paket and "Treffer " not in paket
