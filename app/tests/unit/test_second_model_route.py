# -*- coding: utf-8 -*-
"""Die Software kann beides: lokales LM Studio und einen Fremdanbieter.

Lokal bleibt die Voreinstellung und das Verkaufsargument. Ein zweiter Weg
ist trotzdem noetig, und zwar aus einem gemessenen Grund: am 2026-08-30
starb der Strom des lokal ueber eine Bruecke angebundenen Modells
reproduzierbar mitten in der Generierung, drei von drei Laeufen. Ein
zweiter, unabhaengiger Weg zum Modell ist die einzige Gegenmassnahme, die
nicht am selben Ausfall haengt.

Der EINZIGE Riegel war eine Heuristik in AppConfig.validate: sie hielt
jeden Pfad mit /api/v1 fuer eine CandyConc-Backend-URL. OpenRouter und
andere OpenAI-kompatible Anbieter benutzen denselben Praefix
(https://openrouter.ai/api/v1/chat/completions). Alles andere war bereits
richtig gebaut: _get_llm_headers liest COPILOT_API_KEY und baut daraus den
Bearer, und _is_local_lm_studio_endpoint liefert fuer einen Fremdhost False,
womit der Modell-Preflight korrekt entfaellt.

Nachgewiesen wurde der Weg END-TO-END durch den Produktclient, nicht nur an
der Konfiguration: call_llm gegen deepseek-v4-flash-0731 lieferte in 3,8 s
die Antwort, und das model-Feld der Antwort trug den angeforderten Namen.
"""

from __future__ import annotations

import pytest

from candyconc.config import AppConfig


def _konfig(**felder) -> AppConfig:
    grund = {
        "CANDYCONC_BACKEND_URL": "http://127.0.0.1:8010",
        "COPILOT_MODEL": "irgendein-modell",
    }
    grund.update(felder)
    return AppConfig(**grund)


class TestZweiterModellweg:
    def test_openrouter_endpunkt_wird_akzeptiert(self):
        k = _konfig(COPILOT_ENDPOINT="https://openrouter.ai/api/v1/chat/completions")
        k.validate()

    @pytest.mark.parametrize("endpunkt", [
        "https://openrouter.ai/api/v1/chat/completions",
        "https://api.together.xyz/v1/chat/completions",
        "http://localhost:1234/v1/chat/completions",
        "http://127.0.0.1:1234/api/v1/chat",
    ])
    def test_gaengige_modellendpunkte_gehen_durch(self, endpunkt):
        """Lokal UND fremd, mit und ohne /api/v1 im Pfad."""
        _konfig(COPILOT_ENDPOINT=endpunkt).validate()

    @pytest.mark.parametrize("endpunkt", [
        "http://127.0.0.1:8010/api/v1/analysis/collocates",
        "http://127.0.0.1:8010/api/v1/corpora",
    ])
    def test_die_backend_verwechslung_bleibt_gefangen(self, endpunkt):
        """Die eigentliche Absicht der Heuristik bleibt erhalten.

        Wer COPILOT_ENDPOINT auf eine Route des eigenen Backends richtet,
        bekommt weiterhin einen sprechenden Fehler statt eines
        unverstaendlichen GET auf /v1/chat/completions.
        """
        with pytest.raises(RuntimeError, match="COPILOT_ENDPOINT"):
            _konfig(COPILOT_ENDPOINT=endpunkt).validate()

    def test_gleicher_host_wie_das_backend_bleibt_gefangen(self):
        """Die praezise Pruefung, die es schon gab, faengt den Rest."""
        with pytest.raises(RuntimeError, match="same host"):
            _konfig(
                COPILOT_ENDPOINT="http://127.0.0.1:8010/v1/chat/completions",
                CANDYCONC_BACKEND_URL="http://127.0.0.1:8010",
            ).validate()


class TestFremdanbieterBrauchtKeinenPreflight:
    def test_fremder_host_gilt_nicht_als_lokales_lm_studio(self):
        """Sonst wuerde der Modell-Preflight gegen /v1/models laufen, den ein
        Fremdanbieter nicht in derselben Form fuehrt."""
        from candyconc.services.llm_client import _is_local_lm_studio_endpoint
        assert not _is_local_lm_studio_endpoint(
            "https://openrouter.ai/api/v1/chat/completions")
        # Positive Klasse: lokal muss weiterhin als lokal gelten, sonst
        # entfiele die Wache gegen still substituierte Modelle.
        assert _is_local_lm_studio_endpoint("http://localhost:1234/v1/chat/completions")

    def test_der_schluessel_wird_zum_bearer(self, monkeypatch):
        from candyconc.services import llm_client
        monkeypatch.setattr(llm_client, "get_config",
                            lambda name, default=None: "sk-test-123"
                            if name == "COPILOT_API_KEY" else default)
        assert llm_client._get_llm_headers() == {"Authorization": "Bearer sk-test-123"}
