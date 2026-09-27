"""The evidence package includes the visible table rows and complete profiles."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul


def _keyness(gesehen=20, erhoben=60):
    reihen = [{"word": f"w{i}", "direction": "target", "target_freq": 100 + i, "reference_freq": 5,
               "target_per_million": 231.66 + i, "reference_per_million": 38.39, "diff_per_million": 1.0,
               "ll_signed": 9.9, "log_ratio": 2.59, "log_ratio_ci_low": 2.29, "log_ratio_ci_high": 2.88,
               "lrc": 1.8, "q_value": 0.0, "low_reliability": False, "chi2_cell": 3.3, "bic": 7.7}
              for i in range(erhoben)]
    flaeche = []
    for i in range(gesehen):
        flaeche += [f"rows[{i}] {{'word': 'w{i}', ...}}", f"kwic[{i}] w{i}"]
    return {"id": "E_keyness_10", "tool": "keyness", "query": "{}", "status": "success",
            "grounding_surface": flaeche + ["rows_seen=60"],
            "fact_surface": {"rows_seen": erhoben, "rows": reihen}}


def _docset():
    profil = {"doc_len": {"min": 1}, "axes": {"ref_doc": "7303 Werte, Tokenanteile: 16854 0.1%, +7300 weitere",
                                              "profile_id": "12 Werte, Tokenanteile: " + "x" * 400}}
    return {"id": "E_create_docset_2", "tool": "create_docset", "query": "{}", "status": "success",
            "grounding_surface": ["docset_id=abc", "label=AI", "profile={'doc_len': {'min': 1}, 'axes': {'profile_id': '12 We...",
                                  "doc_count=87636"],
            "fact_surface": {"label": "AI", "profile": profil, "docset_id": "abc", "doc_count": 87636}}


def test_tabelle_zeigt_alle_gesehenen_zeilen_mit_den_feldern_der_modellsicht(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    zeilen = [z.strip() for z in modul.evidenz_paket_text([_keyness()]).splitlines()]
    tabelle = [z for z in zeilen if z.startswith("Zeile ")]
    assert len(tabelle) == 20
    assert "target_per_million=246.66" in tabelle[15] and "log_ratio_ci_low=2.29" in tabelle[15]
    assert "chi2_cell" not in tabelle[15], "Nur die Felder der Modellsicht."
    assert any("40 weitere Zeilen" in z for z in zeilen)


def test_docset_profil_steht_ganz_im_paket(monkeypatch):
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "1")
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "1")
    paket = modul.evidenz_paket_text([_docset()])
    assert "7303 Werte" in paket
    assert "profile={" not in paket


def test_klammern_der_fundstelle_machen_kein_zitat_unverifizierbar():
    item = {"grounding_surface": ["kwic[0] Behörden in Schleswig-Holstein nicht verpflichtet , sondern lediglich"]}
    text = "Beleg: „Behörden in Schleswig-Holstein nicht verpflichtet, [sondern] lediglich“."
    assert modul._unverifizierte_zitate(text, [item]) == []


def test_korpuskarte_sagt_dass_lemma_die_wortform_ist():
    # A7: der Index ist ohne Lemmatisierer gebaut (spacy_model blank:de), und
    # das Modell hielt "eigentliche" fuer ein Lemma ueber alle Formen.
    from candyconc.candyconc_copilot.prompt_layout import _render_corpus_card
    from candyconc.candyconc_copilot.recipe_runtime import corpus_card_from_context

    karte = corpus_card_from_context({"corpus_id": "ping", "corpus_attributes": ["word", "lemma"],
                                      "corpus_lemma_ist_wortform": True})
    assert any(z.startswith("lemma: kleingeschriebene Wortform") for z in _render_corpus_card(karte))
    ohne = corpus_card_from_context({"corpus_id": "ping", "corpus_attributes": ["word", "lemma"]})
    assert not any(z.startswith("lemma:") for z in _render_corpus_card(ohne))
