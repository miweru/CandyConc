"""Use the model draft as the answer when the model ends research voluntarily."""

import asyncio

from candyconc.candyconc_copilot import interpretation_synthesis as modul


class _Sitzung:
    session_id = "probe"


class _Orchestrator:
    def __init__(self, selbst_beendet):
        self._ra_deutung_abgegeben = selbst_beendet
        self._active_analysis_contract = {}
        self.session = _Sitzung()


def _fahre(monkeypatch, *, schalter, selbst_beendet, entwurf):
    synthesen = []

    async def _synthese(*_a, **_k):
        synthesen.append(1)
        return "SYNTHESE"

    async def _durchreichen(_orch, _ts, _bus, text, _items):
        return text, []

    monkeypatch.setenv("CANDYCONC_ENTWURF_ALS_ANTWORT", schalter)
    monkeypatch.setattr(modul, "_einfache_synthese", _synthese)
    monkeypatch.setattr(modul, "_verankere", _durchreichen)
    monkeypatch.setattr(modul, "_publiziere_belegkarte", lambda *_a: None)
    monkeypatch.setattr(modul, "zwischenstand", lambda *a, **k: None)
    monkeypatch.setattr(modul, "gutachten_aktiv", lambda: False)
    text = asyncio.run(modul.fuehre_deutungs_synthese_aus(
        _Orchestrator(selbst_beendet), object(), object(), [{}], entwurf=entwurf))
    return text, len(synthesen)


def test_selbst_beendet_liefert_den_entwurf_ohne_deutungsaufruf(monkeypatch):
    text, synthesen = _fahre(monkeypatch, schalter="1", selbst_beendet=True,
                             entwurf="Kernbefund: 3082 Formen {{ev:E_query_count_5.total}}.")
    assert synthesen == 0, "Der Entwurf des Modells ist die Antwort, kein zweiter Aufruf."
    assert text.startswith("Kernbefund: 3082 Formen {{ev:E_query_count_5}}")


def test_ohne_eigenes_ende_schreibt_die_synthese(monkeypatch):
    # Lief das Kontextfenster vorher voll, gibt es keinen Entwurf, der aus
    # dem eigenen Ende stammt. Dann bleibt die Synthese der Weg.
    text, synthesen = _fahre(monkeypatch, schalter="1", selbst_beendet=False,
                             entwurf="halber Text")
    assert (text, synthesen) == ("SYNTHESE", 1)


def test_leerer_entwurf_schreibt_die_synthese(monkeypatch):
    text, synthesen = _fahre(monkeypatch, schalter="1", selbst_beendet=True, entwurf="  ")
    assert (text, synthesen) == ("SYNTHESE", 1)


def test_schalter_aus_bleibt_beim_bisherigen_weg(monkeypatch):
    text, synthesen = _fahre(monkeypatch, schalter="0", selbst_beendet=True,
                             entwurf="Kernbefund steht hier.")
    assert (text, synthesen) == ("SYNTHESE", 1)


def test_feldverweis_wird_elementverweis():
    ein = ("2994 {{ev:E_query_count_5.total}} und 551.103 "
           "{{ev:E_query_count_2.schreibung_gefaltet}}, dazu {{ev:E_create_docset_8}}.")
    assert modul.entwurf_marker_vereinfachen(ein) == (
        "2994 {{ev:E_query_count_5}} und 551.103 {{ev:E_query_count_2}}, "
        "dazu {{ev:E_create_docset_8}}.")
