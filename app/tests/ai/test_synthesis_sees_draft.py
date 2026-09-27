"""Die Synthese sieht auf Schalter den Entwurf aus der Werkzeugphase.

Ohne Schalter bleibt der Deutungsaufruf zeichengleich, mit Schalter steht der
Entwurf mit einfachen Belegmarken hinter der Evidenz.
"""

from candyconc.candyconc_copilot import interpretation_synthesis as modul

_ENTWURF = "Elf von zwölf KI‑Varianten liegen darunter {{ev:E_query_count_28.per_million}}."


def test_abgeschaltet_bleibt_der_aufruf_gleich(monkeypatch):
    monkeypatch.setenv("CANDYCONC_SYNTHESE_MIT_ENTWURF", "0")
    vorher = modul.deutungs_synthese_messages("Frage?", "EVIDENZ", "KORPUS")
    nachher = modul.deutungs_synthese_messages("Frage?", "EVIDENZ", "KORPUS", _ENTWURF)
    assert vorher == nachher


def test_vorgabe_ist_an(monkeypatch):
    """Gemessen an fuenf Nachspielen auf Qwen."""
    monkeypatch.delenv("CANDYCONC_SYNTHESE_MIT_ENTWURF", raising=False)
    assert modul.synthese_mit_entwurf_aktiv()


def test_mit_schalter_steht_der_entwurf_hinter_der_evidenz(monkeypatch):
    monkeypatch.setenv("CANDYCONC_SYNTHESE_MIT_ENTWURF", "1")
    system, nutzer = modul.deutungs_synthese_messages("Frage?", "EVIDENZ", "KORPUS", _ENTWURF)
    text = nutzer["content"]
    assert text.index("EVIDENZ") < text.index("ENTWURF AUS DER WERKZEUGPHASE:")
    assert "{{ev:E_query_count_28}}" in text and ".per_million}}" not in text
    assert "ENTWURF:" in system["content"]


def test_mit_schalter_ohne_entwurf_bleibt_der_aufruf_gleich(monkeypatch):
    monkeypatch.setenv("CANDYCONC_SYNTHESE_MIT_ENTWURF", "1")
    mit = modul.deutungs_synthese_messages("Frage?", "EVIDENZ", "KORPUS", "")
    monkeypatch.setenv("CANDYCONC_SYNTHESE_MIT_ENTWURF", "0")
    ohne = modul.deutungs_synthese_messages("Frage?", "EVIDENZ", "KORPUS")
    assert mit == ohne
