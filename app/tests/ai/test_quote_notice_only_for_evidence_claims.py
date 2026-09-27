"""Der Zitathinweis prueft nur Anfuehrungen, die sich als Korpuszeile ausgeben.

Kandidat 4 (8689dde5c3), Regression: Unter den Antworten zu Frage 8, 13
und 14 standen Hinweise auf „unbelegte wörtliche Zitate“, gemeldet waren
druckbare Saetze der Antwort, Etiketten und Distanzzitate. Wortlaute aus den
Antworten.
"""

from candyconc.candyconc_copilot import interpretation_synthesis as modul


_KWIC = {
    "id": "E_run_cqlf_query_7",
    "tool": "run_cqlf_query",
    "query": '{"query": "Sprache"}',
    "grounding_surface": ['kwic[0] "Hier sind vier Nachrichten in Leichter Sprache ."'],
}


def test_druckbarer_satz_mit_belegen_ist_eigene_stimme():
    text = ("Druckbar formuliert lautet der Befund: „Die untersuchten KI-Umschreibungen verwenden "
            "deswegen 12,8 [[beleg:E_query_count_8]] statt 124,2 [[beleg:E_query_count_9]] pro Million.“")
    assert modul._unverifizierte_zitate(text, [_KWIC]) == []


def test_druckbarer_satz_ohne_beleg_ist_eigene_stimme():
    text = "Druckbar: **„Die Modelle deklarieren und strukturieren Leichte Sprache; die Menschen schreiben sie still.“**"
    assert modul._unverifizierte_zitate(text, [_KWIC]) == []


def test_distanzzitat_ist_eigene_stimme():
    text = "Die KI-Texte verfehlen easy_language nicht im Sinne von „falsches Register“, sondern treffen eine andere Variante."
    assert modul._unverifizierte_zitate(text, [_KWIC]) == []


def test_suchbegriff_mit_zaehlbeleg_ist_keine_korpuszeile():
    text = "Die längere Formel „zusammenfassend lässt sich sagen“ ist selten (AI_blog 198 [[beleg:E_query_count_28]])."
    assert modul._unverifizierte_zitate(text, [_KWIC]) == []


def test_erfundene_zeile_mit_zeilenbeleg_wird_gemeldet():
    text = "Die Modelle schreiben Kopfsätze wie „Hier sind fünf Meldungen in Leichter Sprache.“ [[beleg:E_run_cqlf_query_7]]."
    assert modul._unverifizierte_zitate(text, [_KWIC]) == ["Hier sind fünf Meldungen in Leichter Sprache."]


def test_echte_zeile_mit_zeilenbeleg_bleibt_still():
    text = "Die Modelle schreiben Kopfsätze wie „Hier sind vier Nachrichten in Leichter Sprache.“ [[beleg:E_run_cqlf_query_7]]."
    assert modul._unverifizierte_zitate(text, [_KWIC]) == []


def test_eigene_stimme_zaehlt_nur_im_eigenen_satz():
    """Kandidat 4, Frage 4: vor der Korpuszeile stand „im selben Satz“ im Satz davor."""
    text = ("Später im selben Satz „außerdem“. - Menschlicher Originaltext: "
            "„Europol hat ein automatisiertes Werkzeug entwickelt und will es ausbauen“.")
    assert len(modul._unverifizierte_zitate(text, [_KWIC])) == 1


def test_schraegstrich_als_umbruch_im_zitat():
    """A slash can represent a line break while the quoted words remain strictly checked."""
    zeile = {"id": "E_run_cqlf_query_10", "tool": "run_cqlf_query", "query": '{"query": "bedeutet"}',
             "grounding_surface": ['kwic[0] "Die Wahl ist : allgemein [Das bedeutet] : Niemand wird ausgeschlossen ."']}
    text = "Menschlich: „Die Wahl ist: allgemein / Das bedeutet: Niemand wird ausgeschlossen.“ [[beleg:E_run_cqlf_query_10]]."
    assert modul._unverifizierte_zitate(text, [zeile]) == []
    falsch = "Menschlich: „Die Wahl ist: geheim / Das bedeutet: Niemand wird ausgeschlossen.“ [[beleg:E_run_cqlf_query_10]]."
    assert len(modul._unverifizierte_zitate(falsch, [zeile])) == 1
