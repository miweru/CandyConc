# -*- coding: utf-8 -*-
"""Retries avoid repeating a timed-out call on the same engine and model.

Template requirements are known before the first request, and route
fallback does not repeat a call whose duration was already exhausted."""

from __future__ import annotations

from candyconc.services.llm_client import (
    _LLMRoute,
    _system_first_only,
    _should_try_alternate_route,
    LLMErrorKind,
    LLMRequestError,
)


def _fehler(kind: str) -> LLMRequestError:
    return LLMRequestError(kind=kind, message="x", endpoint="e")


LOKAL_CHAT = _LLMRoute(
    endpoint="http://127.0.0.1:1234/v1/chat/completions", model="qwen3.8-27b"
)
LOKAL_RESP = _LLMRoute(
    endpoint="http://127.0.0.1:1234/v1/responses", model="qwen3.8-27b"
)
FREMD = _LLMRoute(endpoint="https://api.fremd.example/v1/chat", model="anderes")
ANDERES_MODELL = _LLMRoute(
    endpoint="http://127.0.0.1:1234/v1/responses", model="llama-70b"
)


class TestKeinWechselNachTimeoutAufDemselbenMotor:
    def test_timeout_gleiche_maschine_kein_wechsel(self):
        assert not _should_try_alternate_route(
            _fehler(LLMErrorKind.TIMEOUT),
            aktuelle=LOKAL_CHAT,
            naechste=LOKAL_RESP,
        )

    def test_timeout_anderer_host_weiter_erlaubt(self):
        """Dort kann die Ursache wirklich an der Route liegen."""
        assert _should_try_alternate_route(
            _fehler(LLMErrorKind.TIMEOUT), aktuelle=LOKAL_CHAT, naechste=FREMD
        )

    def test_timeout_anderes_modell_weiter_erlaubt(self):
        assert _should_try_alternate_route(
            _fehler(LLMErrorKind.TIMEOUT),
            aktuelle=LOKAL_CHAT,
            naechste=ANDERES_MODELL,
        )

    def test_protokollfehler_wechselt_weiterhin(self):
        """Nur der Timeout-Fall ist betroffen, sonst nichts."""
        for kind in (
            LLMErrorKind.ENDPOINT_NOT_FOUND,
            LLMErrorKind.CAPABILITY_MISMATCH,
            LLMErrorKind.INVALID_RESPONSE,
            LLMErrorKind.MEDIA_UNSUPPORTED,
        ):
            assert _should_try_alternate_route(
                _fehler(kind), aktuelle=LOKAL_CHAT, naechste=LOKAL_RESP
            ), kind

    def test_ohne_routenangabe_unveraendert(self):
        """Rueckwaertsvertraeglich: ohne Kontext bleibt die alte Antwort."""
        assert _should_try_alternate_route(_fehler(LLMErrorKind.TIMEOUT))

    def test_nicht_wechselnde_fehler_bleiben_nicht_wechselnd(self):
        assert not _should_try_alternate_route(
            _fehler(LLMErrorKind.AUTH_FAILED),
            aktuelle=LOKAL_CHAT,
            naechste=FREMD,
        )


class TestTemplateWissenVorbelegt:
    def test_qwen3_ohne_fehlversuch_bekannt(self):
        assert _system_first_only("qwen3.8-27b")
        assert _system_first_only("Qwen3-32B")

    def test_fremdes_modell_nicht_vorbelegt(self):
        """Sonst wuerde die Umschreibung Modelle treffen, die sie nicht brauchen."""
        assert not _system_first_only("gpt-oss-120b")
        assert not _system_first_only("llama-70b")
        assert not _system_first_only("")

    def test_laufzeitlernen_bleibt(self):
        """Die Vorbelegung ersetzt das Lernen nicht, sie ergaenzt es.

        Praedikat UND Menge werden ueber DASSELBE Modulobjekt geholt. Die
        Vorfassung importierte die Funktion auf Modulebene und mutierte die
        Menge ueber ``candyconc.services.llm_client``: im vollen Suitenlauf
        sind das zwei verschiedene Objekte, weil tests/conftest.py Module
        stubbt und neu laedt. Isoliert und in tests/ai gruen, im Gesamtlauf
        rot -- eine Annahme ueber Modulidentitaet, nicht ueber Verhalten.
        """
        from candyconc.services import llm_client as lc

        assert not lc._system_first_only("erfundenes-modell-x")
        lc._SYSTEM_FIRST_ONLY_MODELS.add("erfundenes-modell-x")
        try:
            assert lc._system_first_only("erfundenes-modell-x")
        finally:
            lc._SYSTEM_FIRST_ONLY_MODELS.discard("erfundenes-modell-x")
        assert not lc._system_first_only("erfundenes-modell-x")
