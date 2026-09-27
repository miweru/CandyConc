# -*- coding: utf-8 -*-
"""P3.2: freie Gewinne, einzeln geprueft.

Drei Hebel standen im Plan. Zwei sind umgesetzt, einer ist bewusst
gestrichen, und alle drei sind hier festgehalten, damit keiner davon
unbemerkt kippt.
"""

from __future__ import annotations

import asyncio


from candyconc.services import llm_client as lc


class TestVerbindungenWiederverwenden:
    def test_derselbe_loop_bekommt_denselben_client(self):
        """Vorher baute JEDER Modellaufruf eine neue Verbindung auf."""

        async def lauf():
            a = lc._shared_http_client()
            b = lc._shared_http_client()
            assert a is b
            assert not a.is_closed
            await lc.aclose_http_clients()
            return a

        client = asyncio.run(lauf())
        assert client.is_closed

    def test_ein_neuer_loop_bekommt_einen_eigenen_client(self):
        """Ein httpx-Client bindet sich an seinen Loop.

        Ein prozessweiter Client waere im zweiten Lauf an einen toten Loop
        gebunden. Genau deshalb ist der Loop der Schluessel.

        Verglichen wird die Identitaet der GEHALTENEN Objekte, nicht ihre
        Adresse. Die frueher hier verglichenen ``id()``-Werte stammten von
        Objekten, die zwischen den beiden Laeufen freigegeben sein konnten,
        und CPython vergibt die Adresse dann erneut. Gemessen am
        2026-08-24: 48 von 60 Durchlaeufen kollidierten so, mit gehaltener
        Referenz 0 von 60. Der Test war damit zu vier Fuenfteln eine
        Zufallsprobe und fiel entsprechend nur im vollen Lauf um.
        """

        async def hole():
            return lc._shared_http_client()

        erst = asyncio.run(hole())
        zweit = asyncio.run(hole())
        assert erst is not zweit
        asyncio.run(lc.aclose_http_clients())

    def test_ein_geschlossener_client_wird_ersetzt(self):
        async def lauf():
            a = lc._shared_http_client()
            await a.aclose()
            b = lc._shared_http_client()
            assert b is not a
            assert not b.is_closed
            await lc.aclose_http_clients()

        asyncio.run(lauf())

    def test_keepalive_ist_wirklich_konfiguriert(self):
        """Sonst waere die Wiederverwendung ein leeres Versprechen."""

        async def lauf():
            client = lc._shared_http_client()
            limits = client._transport._pool._max_keepalive_connections
            await lc.aclose_http_clients()
            return limits

        assert asyncio.run(lauf()) >= 8


class TestCallTimeoutUnterTurnbudget:
    """Der Aufruf-Timeout bleibt unter dem Turn-Budget, WENN es eines gibt.

    Seit dem 2026-09-20 ist "kein Budget" die Vorgabe (Nutzervorgabe: "Ich
    will keine Max Time"). Dann gibt es nichts, worunter etwas bleiben
    muesste, und die Deckelung entfaellt. Der geschuetzte Defekt bleibt
    derselbe und wird mit gesetztem Budget geprueft: 120 plus 10 gegen ein
    Budget von 120 laesst den harten Turn-Abbruch feuern statt des
    Aufruf-Timeouts mit Wiederholung, und die Nutzerin bekommt gar keine
    Antwort statt einer knappen.
    """

    def _budget(self):
        from candyconc.services.backend.copilot_helpers import _copilot_max_time_sec

        return _copilot_max_time_sec()

    def test_ohne_budget_deckelt_nichts(self, monkeypatch):
        monkeypatch.delenv("CANDYCONC_COPILOT_MAX_TIME_SEC", raising=False)
        assert self._budget() is None
        assert lc._unter_dem_turnbudget(10_000.0) == 10_000.0

    def test_mit_budget_bleibt_der_normale_call_darunter(self, monkeypatch):
        monkeypatch.setenv("CANDYCONC_COPILOT_MAX_TIME_SEC", "600")
        budget = float(self._budget())
        timeout = lc._get_llm_timeout()
        assert timeout is not None
        assert timeout < budget, f"{timeout} >= Turn-Budget {budget}"

    def test_mit_budget_bleibt_auch_der_schema_zuschlag_darunter(self, monkeypatch):
        monkeypatch.setenv("CANDYCONC_COPILOT_MAX_TIME_SEC", "600")
        budget = float(self._budget())
        timeout = lc._get_llm_timeout(extra_seconds=10.0)
        assert timeout is not None
        assert timeout < budget, f"{timeout} >= Turn-Budget {budget}"

    def test_kleinere_werte_bleiben_unangetastet(self):
        """Die Schranke deckelt, sie hebt nicht an."""
        gedeckelt = lc._unter_dem_turnbudget(5.0)
        assert gedeckelt == 5.0

    def test_abschalten_bleibt_abschalten(self, monkeypatch):
        """timeout=0 heisst weiterhin "kein Timeout", nicht "100 Sekunden"."""
        monkeypatch.setattr(lc.APP_CONFIG, "COPILOT_TIMEOUT", 0, raising=False)
        assert lc._get_llm_timeout() is None


class TestPreflightCacheBleibtAus:
    def test_ttl_default_ist_null(self):
        """Der Preflight-Cache ist standardmäßig deaktiviert."""
        from candyconc.config import get as get_config

        assert str(
            get_config("CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TTL_SEC", "0")
        ).strip() in {"0", "0.0", ""}
