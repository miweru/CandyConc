"""A synthesis restart preserves the last attempt without duplicating the answer."""

import asyncio

from candyconc.candyconc_copilot import interpretation_synthesis as modul

ANLAUF = ('Nein, als pauschales „KI gegen Mensch" trägt der Befund nicht, die Richtung stimmt fast '
          'überall, die Höhe kommt aus zwei Modellen und zwei Registern.\n\nIch nehme einen '
          'belastbaren Kandidaten: **Fazit** als KI-Mehrgebrauch. Korpusweit stehen '
          '12100{{ev:E_query_count_5}} AI-Treffer mit 114,8{{ev:E_query_count_5}} pro Million Wörter.')
ABBRUCH = (' Auch human ist „Fazit" schon kein Allgemeinwort: 71,4%{{ev:E_query_count_6}} der ohnehin '
           'nur 126 Treffer liegen im blog_essay. Die KI vervielfacht also eine bereits '
           'registergebundene human-R')
SCHLUSS = ' Die KI vervielfacht also eine bereits registergebundene human-Routine.'
AUFGEZEICHNET = ANLAUF + ABBRUCH + "\n\n" + ANLAUF + ABBRUCH[:-1] + "Routine." + SCHLUSS


class _Orchestrator:
    def __init__(self, inhalt):
        self.inhalt = inhalt

    async def _ra_call_llm_with_recovery(self, _ts, _bus, invoker):
        return {"choices": [{"message": {"content": self.inhalt}}]}

    def _ra_invoke_llm(self, *_a, **_k):
        return None

    def _extract_message_content(self, text):
        return text


def _ein_call(inhalt, monkeypatch):
    aufgezeichnet = {}
    monkeypatch.setattr(modul, "zwischenstand",
                        lambda name, text, **_k: aufgezeichnet.__setitem__(name, text))
    monkeypatch.setattr(modul, "_sitzung", lambda _o: "probe")
    text = asyncio.run(modul._ein_call(_Orchestrator(inhalt), object(), object(), []))
    return text, aufgezeichnet


def test_der_letzte_anlauf_ist_die_antwort(monkeypatch):
    text, aufgezeichnet = _ein_call(AUFGEZEICHNET, monkeypatch)
    assert text.count("Nein, als pauschales") == 1
    assert "human-R\n" not in text and text.endswith("human-Routine.")
    assert aufgezeichnet["neuansatz_verworfen"].rstrip().endswith("human-R"), (
        "Der verworfene Anlauf wird aufgezeichnet, nicht still entfernt.")


def test_eine_wiederholung_nach_vollstaendigem_satz_bleibt(monkeypatch):
    zusammenfassung = ANLAUF + "\n\nZusammengefasst: " + ANLAUF
    wiederholt = ANLAUF + "\n\n" + ANLAUF
    for inhalt in (zusammenfassung, wiederholt):
        text, aufgezeichnet = _ein_call(inhalt, monkeypatch)
        assert text == inhalt and not aufgezeichnet


def test_eine_kurze_antwort_bleibt_unberuehrt():
    assert modul._letzter_anlauf("Kurz. Kurz.") == "Kurz. Kurz."
