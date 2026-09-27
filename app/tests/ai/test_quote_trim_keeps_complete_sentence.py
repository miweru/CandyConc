"""Die Kappung offener Spannen trifft nur abgebrochene Zeilen.

K11-Lauf A, Frage 20 (r5b-konkordanz-belegqualitaet, Sitzung
0ea7dd34d7b247e9b1ece730ac39701b): die Synthese endete mit einem
vollstaendigen Satz, in dem das Modell „`„…“-Mengen“ einen Backtick offen
liess. Die Zahl der Backticks war ungerade, und die Politur schnitt ab dem
letzten Backtick bis zum Zeilenende ab. Die Antwort endete mit
„ausgeschlossen ist dagegen eine pipe-tabellarische `Herausforderung“.
"""

from candyconc.candyconc_copilot import recipe_runtime as rr

_K11_A_FRAGE_20 = (
    "Unsicherheit in einem Satz: Überlappung zwischen `#`-, `*`- und "
    "`„…“-Mengen sowie Dubletten innerhalb desselben Dokuments wurden nicht "
    "disjunkt gemessen, Größenordnung des Fehlers wenige Prozentpunkte nach "
    "oben, ausgeschlossen ist dagegen eine pipe-tabellarische "
    "`Herausforderung`-Stelle mit 0 Treffern [[beleg:E_run_cqlf_query_9]] "
    "sowie jede korpusweite Hochrechnung aus 5.921 als unabhängigen "
    "Beobachtungen."
)


def test_ein_vollstaendiger_letzter_satz_bleibt_ganz():
    text = "Befund: klar.\n\n" + _K11_A_FRAGE_20
    assert rr._trim_dangling_quote_spans(text) == text


def test_ein_satzende_vor_der_belegmarke_zaehlt():
    text = "Befund: klar.\n- Beleg: „Deutschland geht unter.“ und das `Paket hält. [[beleg:E_1]]"
    assert rr._trim_dangling_quote_spans(text) == text


def test_eine_abkuerzung_am_ende_ist_kein_satzende():
    # tests/ai/test_h9_c2_landings_polish.py: Stream-Abbruch nach „Sie u.“
    text = "Match im Kontext „Menschen in Arbeit bringen \"??? Sie u."
    assert rr._trim_dangling_quote_spans(text) == "Match im Kontext"


def test_die_politur_behaelt_den_satz():
    poliert, _ = rr.final_answer_polish("Befund: klar.\n\n" + _K11_A_FRAGE_20,
                                        deckung_wache=False)
    assert "als unabhängigen Beobachtungen." in poliert


def test_ein_abgebrochener_backtick_wird_weiter_gekappt():
    text = 'Kernbefund: klar.\n- Query: `[word="X"]'
    assert rr._trim_dangling_quote_spans(text) == "Kernbefund: klar.\n- Query:"


def test_ein_abgebrochenes_zitat_wird_weiter_gekappt():
    text = "Kernbefund: klar.\n- Beleg: „Deutschland geht"
    assert rr._trim_dangling_quote_spans(text) == "Kernbefund: klar.\n- Beleg:"
