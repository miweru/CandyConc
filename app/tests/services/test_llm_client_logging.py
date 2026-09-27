import os
import unittest
from unittest.mock import patch

import httpx

import candyconc.services.llm_client as llm_client


class FakeResponse:
    def __init__(self, data):
        self._data = data
        # llm_client inspects resp.status_code before raise_for_status
        # (src/candyconc/services/llm_client.py, _post_json_with_retry)
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class TestLLMClientLogging(unittest.IsolatedAsyncioTestCase):
    def test_lm_link_keepalive_400_is_retryable_transport_failure(self):
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
        messages = (
            "LM Link connection entered error state peer_keepalive_timeout",
            "LM Link connection closed",
        )
        for message in messages:
            with self.subTest(message=message):
                response = httpx.Response(
                    400,
                    json={"error": message},
                    request=request,
                )

                self.assertTrue(llm_client._retryable_http_response(response))
                with self.assertRaises(httpx.HTTPStatusError) as caught:
                    response.raise_for_status()
                error = llm_client._classify_http_error(
                    str(request.url),
                    caught.exception,
                )
                self.assertEqual(error.kind, llm_client.LLMErrorKind.TRANSPORT)
                self.assertTrue(error.retryable)

    def test_context_window_500_is_not_retried_as_overload(self):
        request = httpx.Request("POST", "http://test/v1/responses")
        response = httpx.Response(
            500,
            text="context_length_exceeded: prompt has too many tokens",
            request=request,
        )

        self.assertFalse(llm_client._retryable_http_response(response))
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
        error = llm_client._classify_http_error(str(request.url), caught.exception)
        self.assertEqual(error.kind, llm_client.LLMErrorKind.CONTEXT_WINDOW_EXCEEDED)
        self.assertFalse(error.retryable)

    def test_engine_protocol_failure_is_typed_for_outer_recovery(self):
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
        response = httpx.Response(
            400,
            json={"error": "Engine protocol predict request failed: fetch failed"},
            request=request,
        )

        self.assertFalse(llm_client._retryable_http_response(response))
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
        error = llm_client._classify_http_error(str(request.url), caught.exception)
        self.assertEqual(error.kind, llm_client.LLMErrorKind.ENGINE_UNAVAILABLE)
        self.assertTrue(error.retryable)
        self.assertIn("kein Modell geladen oder gewechselt", error.message)

    def test_lm_link_route_change_is_transient_and_waits_for_the_model(self):
        """Runde 5, 2026-09-13: 41 Turns starben an 'LM Link route changed'.

        Der geteilte Rechner wechselt Modelle alle 40 bis 90 Minuten, LM
        Studio meldet den Wechsel als HTTP 400. Das ist dieselbe Klasse wie
        'lm link connection closed': vorübergehend, derselbe Aufruf wird
        nach dem Warten auf dasselbe Modell wiederholt, nichts wird geladen.
        """
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
        response = httpx.Response(
            400,
            json={"error": "LM Link route changed from personal:x/1 to personal:x/2"},
            request=request,
        )

        self.assertTrue(llm_client._retryable_http_response(response))
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
        error = llm_client._classify_http_error(str(request.url), caught.exception)
        self.assertEqual(error.kind, llm_client.LLMErrorKind.TRANSPORT)
        self.assertTrue(error.retryable)

    def test_stale_continuation_after_reload_is_typed_for_a_flattened_retry(self):
        """Nach einem Neuladen kennt der Endpunkt die previous_response_id
        nicht mehr. Der Client darf denselben Payload nicht wiederholen, der
        Orchestrator baut die Anfrage ohne Fortsetzung neu."""
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
        response = httpx.Response(
            400,
            json={"error": "previous_response_id resp_abc not found"},
            request=request,
        )

        self.assertFalse(llm_client._retryable_http_response(response))
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
        error = llm_client._classify_http_error(str(request.url), caught.exception)
        self.assertEqual(error.kind, llm_client.LLMErrorKind.STALE_CONTINUATION)
        self.assertTrue(error.retryable)
        self.assertIn("ohne Fortsetzung", error.message)

    def test_stream_failed_event_with_transient_hint_is_retryable(self):
        """Pilotlauf 2026-09-16: vier Turns starben an einem response.failed
        mit 'LM Link connection entered error state peer_keepalive_timeout'.
        Der Ereignis-Zweig prueft nur die Engine-Hinweise, die transienten
        nicht, und wirft deshalb invalid_response ohne Wiederholung. Dieselbe
        Meldung als HTTP-Fehler ist seit jeher transport und wiederholbar."""
        detail = {"message": "LM Link connection entered error state peer_keepalive_timeout",
                  "type": "internal_error"}
        fehler = llm_client._stream_fehler_aus_ereignis(
            "http://127.0.0.1:1234/v1/responses", "response.failed", detail)
        self.assertEqual(fehler.kind, llm_client.LLMErrorKind.TRANSPORT)
        self.assertTrue(fehler.retryable)

    def test_unknown_stream_failure_from_lm_studio_is_retryable(self):
        """UMKEHR 2026-09-16, zweiter Anlauf. Der erste Fix erweiterte eine
        Wortliste um peer_keepalive_timeout, und eine Stunde spaeter starb
        ein Turn an 'Cannot find model of instance reference. The model
        might have already been unloaded.' Dieselbe Klasse, anderer
        Wortlaut. LM Studio meldet Bruecken- und Modellstoerungen als freien
        Text, eine Positivliste bleibt immer unvollstaendig.

        Deshalb gilt jetzt: ein Stream-Fehlerereignis eines LOKALEN
        LM-Studio-Endpunkts ist im Zweifel eine Stoerung und wiederholbar.
        Nicht wiederholbar ist nur, was die ANFRAGE selbst verschuldet, und
        das sind benannte, endliche Faelle."""
        for text in ("Cannot find model of instance reference. The model "
                     "might have already been unloaded.",
                     "irgendein unbekannter Fehler",
                     "socket hang up"):
            fehler = llm_client._stream_fehler_aus_ereignis(
                "http://127.0.0.1:1234/v1/responses", "response.failed",
                {"message": text})
            self.assertTrue(fehler.retryable, text)

    def test_request_faults_in_a_stream_event_stay_unretryable(self):
        """Die Umkehr darf die Anfrage-Fehler nicht mitnehmen: wer dasselbe
        zu lange Fenster noch einmal schickt, bekommt denselben Fehler."""
        for text, art in (
            ("Context size has been exceeded", llm_client.LLMErrorKind.CONTEXT_WINDOW_EXCEEDED),
            ("max_output_tokens is invalid", llm_client.LLMErrorKind.MAX_OUTPUT_TOKENS),
            ("tools are not supported by this model", llm_client.LLMErrorKind.CAPABILITY_MISMATCH),
        ):
            fehler = llm_client._stream_fehler_aus_ereignis(
                "http://127.0.0.1:1234/v1/responses", "response.failed",
                {"message": text})
            self.assertEqual(fehler.kind, art, text)
            self.assertFalse(fehler.retryable, text)

    def test_unknown_http_400_from_lm_studio_is_retryable(self):
        """DRITTER Anlauf derselben Klasse am selben Tag. Der erste erweiterte
        eine Wortliste (peer_keepalive_timeout), der zweite drehte sie fuer
        STREAM-Ereignisse um, und abends starb ein Turn an HTTP 400 mit
        "LM Link client transport disposed". Die Umkehr fehlte im
        HTTP-Pfad, also wieder ein Fix an einer von zwei Naehten."""
        for text in ("LM Link client transport disposed",
                     "Cannot find model of instance reference",
                     "irgendein unbekannter Bridge-Fehler"):
            request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
            response = httpx.Response(400, json={"error": text}, request=request)
            with self.assertRaises(httpx.HTTPStatusError) as caught:
                response.raise_for_status()
            fehler = llm_client._classify_http_error(str(request.url), caught.exception)
            self.assertTrue(fehler.retryable, text)

    def test_request_faults_over_http_stay_unretryable(self):
        for text, art in (
            ("Context size has been exceeded", llm_client.LLMErrorKind.CONTEXT_WINDOW_EXCEEDED),
            ("max_output_tokens is invalid", llm_client.LLMErrorKind.MAX_OUTPUT_TOKENS),
            ("tools are not supported", llm_client.LLMErrorKind.CAPABILITY_MISMATCH),
        ):
            request = httpx.Request("POST", "http://127.0.0.1:1234/v1/responses")
            response = httpx.Response(400, json={"error": text}, request=request)
            with self.assertRaises(httpx.HTTPStatusError) as caught:
                response.raise_for_status()
            fehler = llm_client._classify_http_error(str(request.url), caught.exception)
            self.assertEqual(fehler.kind, art, text)
            self.assertFalse(fehler.retryable, text)

    def test_unknown_http_400_from_a_remote_endpoint_stays_bad_request(self):
        request = httpx.Request("POST", "https://api.example.com/v1/responses")
        response = httpx.Response(400, json={"error": "irgendwas"}, request=request)
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            response.raise_for_status()
        fehler = llm_client._classify_http_error(str(request.url), caught.exception)
        self.assertEqual(fehler.kind, llm_client.LLMErrorKind.BAD_REQUEST)
        self.assertFalse(fehler.retryable)

    def test_unknown_stream_failure_from_a_remote_endpoint_stays_strict(self):
        """Die Umkehr gilt nur lokal. Ein fremder Endpunkt bekommt kein
        Vertrauen, das auf der Kenntnis von LM Studio beruht."""
        fehler = llm_client._stream_fehler_aus_ereignis(
            "https://api.example.com/v1/responses", "response.failed",
            {"message": "irgendein unbekannter Fehler"})
        self.assertEqual(fehler.kind, llm_client.LLMErrorKind.INVALID_RESPONSE)

    def test_stream_failed_event_with_engine_hint_stays_engine_unavailable(self):
        fehler = llm_client._stream_fehler_aus_ereignis(
            "http://127.0.0.1:1234/v1/responses", "response.failed",
            {"message": "Engine protocol predict request failed"})
        self.assertEqual(fehler.kind, llm_client.LLMErrorKind.ENGINE_UNAVAILABLE)
        self.assertTrue(fehler.retryable)

    def test_warte_auf_modell_survives_an_unreachable_endpoint(self):
        """Startet LM Studio neu, ist auch /v1/models weg. Das Warten darf
        daran nicht scheitern, sondern sondiert weiter, bis der Endpunkt
        und dann das Modell zurueck sind. Laedt nichts."""
        import asyncio
        from unittest import mock

        versuche = []

        async def _preflight(route, *, timeout, headers):
            versuche.append(route.model)
            if len(versuche) < 3:
                raise llm_client.LLMRequestError(
                    kind=llm_client.LLMErrorKind.TRANSPORT,
                    message="connection refused", retryable=True)
            return None

        async def _kein_schlaf(_s):
            return None

        with mock.patch.object(llm_client, "_ensure_lm_studio_model_loaded", _preflight), \
             mock.patch.object(llm_client.asyncio, "sleep", _kein_schlaf):
            ok = asyncio.run(llm_client.warte_auf_modell(
                "http://127.0.0.1:1234/v1/responses", "qwen3.8-27b-b", timeout=600.0))
        self.assertTrue(ok)
        self.assertEqual(versuche, ["qwen3.8-27b-b"] * 3)

    def test_warte_auf_modell_gives_up_when_the_model_is_gone_for_good(self):
        import asyncio
        from unittest import mock

        async def _preflight(route, *, timeout, headers):
            raise llm_client.LLMRequestError(
                kind=llm_client.LLMErrorKind.MODEL_NOT_LOADED,
                message="not loaded", retryable=False)

        with mock.patch.object(llm_client, "_ensure_lm_studio_model_loaded", _preflight):
            ok = asyncio.run(llm_client.warte_auf_modell(
                "http://127.0.0.1:1234/v1/responses", "qwen3.8-27b-b", timeout=600.0))
        self.assertFalse(ok)

    def test_schema_is_prompted_even_when_native_structured_output_is_disabled(self):
        schema = {
            "name": "analysis_contract",
            "schema": {
                "type": "object",
                "properties": {"mode": {"type": "string"}},
                "required": ["mode"],
            },
        }
        with patch.object(llm_client.APP_CONFIG, "USE_STRUCTURED_OUTPUT", False):
            routes = llm_client._build_route_candidates(
                "http://test/v1/chat/completions",
                "test-model",
                [{"role": "user", "content": "Analysiere das."}],
                tools=[],
                json_schema=schema,
            )

        self.assertTrue(routes)
        self.assertEqual({route.structured_mode for route in routes}, {"prompt_hint"})
        payload = llm_client._build_route_payload(
            routes[0],
            [{"role": "user", "content": "Analysiere das."}],
            [],
            stream=False,
            json_schema=schema,
        )
        self.assertNotIn("response_format", payload)
        self.assertIn("analysis_contract", payload["messages"][0]["content"])

    async def test_debug_logs_payload_and_response(self):
        response = {"choices": [], "usage": {"total_tokens": 1}}

        async def fake_post_json(*_args, **_kwargs):
            return response

        with patch.dict(os.environ, {"COPILOT_ENDPOINT": "http://test/v1/chat/completions"}):
            with patch.object(
                llm_client.APP_CONFIG,
                "COPILOT_ENDPOINT",
                "http://test/v1/chat/completions",
            ):
                with patch.object(llm_client.APP_CONFIG, "COPILOT_MODEL", "test-model"):
                    with patch.object(
                        llm_client,
                        "_post_json_with_retry",
                        fake_post_json,
                    ):
                        with self.assertLogs(llm_client.logger, level="DEBUG") as cm:
                            await llm_client.chat([{"role": "user", "content": "hi"}])

        logs = "\n".join(cm.output)
        # Current contract (src/candyconc/services/llm_client.py, chat()):
        # only the *response* is debug-logged, with choices redacted to a
        # count. Raw payload logging (messages/model) was removed from the
        # client; asserting it would test a deleted feature.
        self.assertIn("LLM response", logs)
        self.assertIn("<0 choices>", logs)
        self.assertIn("usage", logs)


if __name__ == "__main__":
    unittest.main()
