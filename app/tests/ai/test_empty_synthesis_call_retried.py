"""Ein leerer Deutungsaufruf wird wiederholt, nicht durch eine Schablone ersetzt.

Gemessen am 2026-09-17 ueber die Zwischenstaende aller Pilotarme:

    Grundlinie PING   leerer Deutungsaufruf 0 von 19
    Rueckbau PING                           0 von 20
    Paket PING                              6 von 20

Die sechs leeren Aufrufe sind genau die sechs Antworten, die deterministisch
aus der vorhandenen Evidenz gerendert wurden und in der Messdatei als
beantwortete Frage stehen. Sechs der zwanzig verglichenen Paare stellten damit
Deutung gegen Schablone.

Die Paketgroesse ist nicht der Grund: die leeren Aufrufe hatten im Median 139
Belegzeilen, die gelungenen 265.

Die Probe faehrt beide Klassen: leer wird wiederholt und ein Text beim zweiten
Versuch zaehlt, und wer sofort antwortet wird NICHT ein zweites Mal gefragt.
"""

import asyncio

from candyconc.candyconc_copilot import interpretation_synthesis as modul


class _Aufrufzaehler:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = 0

    async def __call__(self, *_a, **_k):
        self.aufrufe += 1
        return self.antworten.pop(0) if self.antworten else ""


def _fahre(antworten, monkeypatch):
    zaehler = _Aufrufzaehler(antworten)
    monkeypatch.setattr(modul, "_ein_call", zaehler)
    monkeypatch.setattr(modul, "zwischenstand", lambda *a, **k: None)
    monkeypatch.setattr(modul, "evidenz_paket_text", lambda _i: "PAKET")
    monkeypatch.setattr(modul, "_sitzung", lambda _o: "probe")

    async def _durchreichen(_orch, _ts, _bus, text, _items):
        return text, []

    monkeypatch.setattr(modul, "_verankere", _durchreichen)
    monkeypatch.setattr(modul, "_setze_beleg_chips", lambda text, _z: text)
    monkeypatch.setattr(modul, "_unverifizierte_zitate", lambda _t, _i: [])

    class _TS:
        normalized_question = "Wie haeufig ist X?"

    text = asyncio.run(modul._einfache_synthese(object(), _TS(), object(), [{}]))
    return text, zaehler.aufrufe


def test_leer_wird_wiederholt_und_der_zweite_versuch_zaehlt(monkeypatch):
    text, aufrufe = _fahre(["", "Die Antwort steht hier."], monkeypatch)
    assert aufrufe == 2, "Nach leerem Inhalt wird noch einmal gefragt."
    assert "Die Antwort steht hier." in text


def test_wer_sofort_antwortet_wird_nicht_zweimal_gefragt(monkeypatch):
    text, aufrufe = _fahre(["Gleich beim ersten Mal."], monkeypatch)
    assert aufrufe == 1, (
        "Ohne diese Haelfte pruefte die Probe nichts: sie waere auch gruen, "
        "wenn JEDER Aufruf wiederholt wuerde."
    )
    assert "Gleich beim ersten Mal." in text


def test_dauerhaft_leer_liefert_leer_und_erfindet_nichts(monkeypatch):
    text, aufrufe = _fahre(["", "", ""], monkeypatch)
    assert aufrufe == modul._DEUTUNG_VERSUCHE
    assert text == "", "Bleibt es leer, wird nichts erfunden."
