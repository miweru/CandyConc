"""Preflight permits a grace period for a model already confirmed in the current run.

A different loaded model must not end that grace period. Unconfirmed
model names fail normally, and repeated probes use a stepped interval."""

from __future__ import annotations

import asyncio

import pytest

from candyconc.services import llm_client as lc


@pytest.fixture(autouse=True)
def _sauberer_cache(monkeypatch):
    monkeypatch.setattr(lc, "_LM_STUDIO_MODEL_CACHE", {})
    monkeypatch.setattr(lc, "_LM_STUDIO_LAST_CONFIRMED_MODELS", {})
    monkeypatch.setattr(lc, "_config_bool", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "_is_local_lm_studio_endpoint", lambda _e: True)
    # Kein echtes Warten im Test, aber die Abstaende werden protokolliert.
    lc._TEST_ABSTAENDE = []

    async def _schlaf(sekunden):
        lc._TEST_ABSTAENDE.append(float(sekunden))

    monkeypatch.setattr(lc.asyncio, "sleep", _schlaf)


def _route():
    # Die ECHTE Endpunktform. Mit "/v1" allein liefert
    # _models_endpoint_for_route None, und previously_confirmed waere
    # immer False. Der Test haette dann seine eigene Erfindung geprueft.
    return lc._LLMRoute(
        endpoint="http://127.0.0.1:1234/v1/chat/completions", model="ziel"
    )


def _listen(monkeypatch, folge):
    """``folge`` ist die Liste der Modellmengen je Sondierung."""

    zustand = {"i": 0}

    async def _geladen(_endpoint, *, timeout=None, headers=None):
        i = min(zustand["i"], len(folge) - 1)
        zustand["i"] += 1
        return frozenset(folge[i])

    monkeypatch.setattr(lc, "_lm_studio_loaded_models", _geladen)
    return zustand


def test_bestaetigtes_modell_bekommt_die_nachfrist(monkeypatch):
    """Der gemessene Fall: andere Modelle da, unseres kurz weg."""

    monkeypatch.setattr(
        lc, "_LM_STUDIO_LAST_CONFIRMED_MODELS",
        {"http://127.0.0.1:1234/v1/models": frozenset({"ziel"})},
    )
    _listen(monkeypatch, [
        {"anderes-a", "anderes-b"},
        {"anderes-a", "anderes-b"},
        {"anderes-a", "anderes-b"},
        {"anderes-a", "ziel"},
    ])
    asyncio.run(
        lc._ensure_lm_studio_model_loaded(
            _route(), timeout=8_000_000.0, headers=None
        )
    )
    assert len(lc._TEST_ABSTAENDE) >= 3, (
        "Der Preflight hat nicht gewartet. Genau das kostete im Messlauf "
        "zwei Turns und 40 Minuten gesammelte Evidenz."
    )


def test_unbestaetigtes_modell_scheitert_weiter_schnell(monkeypatch):
    """Auflage (a): ein Tippfehler darf nicht haengen."""

    _listen(monkeypatch, [{"anderes-a", "anderes-b"}])
    with pytest.raises(lc.LLMRequestError) as fehler:
        asyncio.run(
            lc._ensure_lm_studio_model_loaded(
                _route(), timeout=8_000_000.0, headers=None
            )
        )
    assert "not currently loaded" in str(fehler.value.message)
    assert len(lc._TEST_ABSTAENDE) <= 3, (
        f"Ohne vorherige Bestaetigung wurde {len(lc._TEST_ABSTAENDE)} mal "
        "gewartet. Ein falsch geschriebener Modellname haengt dann."
    )


def test_der_sondierabstand_ist_gestaffelt():
    """Auflage (b): kein Dauerlebenszeichen im Log."""

    abstaende = [lc._preflight_probe_delay(a) for a in range(1, 10)]
    assert abstaende == sorted(abstaende), abstaende
    assert abstaende[0] <= 1.0, "Der erste Versuch muss schnell kommen."
    assert abstaende[-1] >= 30.0, (
        "Der Abstand waechst nicht. Jede Sondierung erzeugt eine "
        "httpx-INFO-Zeile, und im Sekundentakt ist eine tote Bruecke von "
        "einer wartenden nicht mehr zu unterscheiden."
    )
    assert max(abstaende) <= 60.0, "Der Abstand ist nicht gedeckelt."
    # Die drei gemessenen Vorfaelle waren binnen rund 150 s vorbei.
    assert sum(abstaende[:8]) >= 120.0, sum(abstaende[:8])


def test_die_leere_liste_verhaelt_sich_unveraendert(monkeypatch):
    """Der Nachbarzweig darf durch die Spiegelung nichts verlieren."""

    monkeypatch.setattr(
        lc, "_LM_STUDIO_LAST_CONFIRMED_MODELS",
        {"http://127.0.0.1:1234/v1/models": frozenset({"ziel"})},
    )
    _listen(monkeypatch, [set(), set(), {"ziel"}])
    asyncio.run(
        lc._ensure_lm_studio_model_loaded(
            _route(), timeout=8_000_000.0, headers=None
        )
    )
    assert len(lc._TEST_ABSTAENDE) >= 2


def test_ohne_endliche_nachfrist_wird_nicht_gewartet(monkeypatch):
    """Die Regression, die ich selbst gebaut und ein Vertragstest gefangen hat.

    Bei ``timeout=None`` ist ``reappearance_grace`` None. Der erste Anlauf
    liess den Zweig trotzdem in die Warteschleife laufen, und weil dann
    weder ``not previously_confirmed`` noch ``grace_exhausted`` je wahr
    wird, lief sie ENDLOS. Die volle Suite blieb bei 95 Prozent stehen,
    und gefangen hat es nicht diese Datei, sondern ein bestehender
    Vertragstest in test_llm_client_streaming.py.

    Ohne endliche Schranke wird deshalb NICHT gewartet, auch bei einem
    bestaetigten Modell nicht.
    """

    monkeypatch.setattr(
        lc, "_LM_STUDIO_LAST_CONFIRMED_MODELS",
        {"http://127.0.0.1:1234/v1/models": frozenset({"ziel"})},
    )
    _listen(monkeypatch, [{"anderes-a"}])
    with pytest.raises(lc.LLMRequestError):
        asyncio.run(
            lc._ensure_lm_studio_model_loaded(
                _route(), timeout=None, headers=None
            )
        )
    assert lc._TEST_ABSTAENDE == [], (
        f"Es wurde {len(lc._TEST_ABSTAENDE)} mal gewartet, obwohl keine "
        "endliche Nachfrist vorliegt. Das ist die Endlosschleife."
    )
