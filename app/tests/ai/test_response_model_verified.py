# -*- coding: utf-8 -*-
"""Die Antwort muss vom angeforderten Modell stammen.

Gemessen am 2026-08-22 gegen LM Studio: eine Anfrage mit
``"model": "gpt-oss-120b"`` wurde beantwortet, ``error`` war ``null``, und
im Antwortfeld ``model`` stand ``qwen3.8-27b``. Der Server substituiert
still, wenn das angeforderte Modell nicht geladen ist.

Fuer einen Messharness ist das die teuerste Sorte Fehler: die Zahlen
entstehen, sie sehen richtig aus, und sie tragen den Namen eines Modells,
das sie nicht erzeugt hat. Ein Kommentar in ``llm_client`` begruendete den
abgeschalteten Preflight-Cache damit, dass diese Pruefung "im Repo ohnehin"
stattfinde. Sie fand nirgends statt.
"""

from __future__ import annotations

import pytest

from candyconc.services.llm_client import (
    LLMErrorKind,
    LLMRequestError,
    _modelle_sind_dasselbe,
    _pruefe_antwortmodell,
)


class TestNamensvergleich:
    @pytest.mark.parametrize(
        "angefordert,geantwortet,gleich",
        [
            ("gpt-oss-120b", "gpt-oss-120b", True),
            # LM Studio qualifiziert denselben Namen mit Quantisierung/Tag.
            ("gpt-oss-120b", "gpt-oss-120b@q4", True),
            ("mod", "mod:tag", True),
            ("mod", "mod/variant", True),
            # Der gemessene Ernstfall.
            ("gpt-oss-120b", "qwen3.8-27b", False),
            # Kein Praefix-Schlupfloch: laenger heisst nicht gleich.
            ("gpt-oss-120b", "gpt-oss-120b-instruct", False),
            ("org/mod", "mod", False),
            # Ohne Angabe laesst sich nichts widerlegen.
            ("", "irgendwas", True),
            ("irgendwas", "", True),
        ],
    )
    def test_vergleich(self, angefordert, geantwortet, gleich):
        assert _modelle_sind_dasselbe(angefordert, geantwortet) is gleich


class TestPruefung:
    def test_substitution_wirft_hart(self):
        """Hart, nicht als Warnung: eine Warnung im Log haette denselben
        Lauf trotzdem als Messung durchgehen lassen."""
        with pytest.raises(LLMRequestError) as fehler:
            _pruefe_antwortmodell(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "gpt-oss-120b"},
                {"model": "qwen3.8-27b", "error": None},
            )
        assert fehler.value.kind is LLMErrorKind.INVALID_RESPONSE
        assert "qwen3.8-27b" in str(fehler.value)
        assert "gpt-oss-120b" in str(fehler.value)

    def test_uebereinstimmung_geht_durch(self):
        _pruefe_antwortmodell(
            "e", {"model": "gpt-oss-120b"}, {"model": "gpt-oss-120b"}
        )

    def test_nichtdikt_wird_ignoriert(self):
        _pruefe_antwortmodell("e", {"model": "x"}, ["kein", "dict"])

    def test_fehlendes_feld_wirft_nicht(self):
        """Nicht jeder Server fuehrt das Feld. Ein fehlendes Feld ist kein
        Beleg fuer Substitution, und ein Fehlalarm waere hier teuer."""
        _pruefe_antwortmodell("e", {"model": "x"}, {"choices": []})


class TestNaehte:
    def test_beide_antwortnaehte_pruefen(self):
        """Verschoben ist nicht behoben: der Stream-Pfad braucht sie auch."""
        import inspect

        from candyconc.services import llm_client

        quelle = inspect.getsource(llm_client)
        assert quelle.count("_pruefe_antwortmodell(") >= 3, (
            "erwartet: Definition plus beide Antwortnaehte"
        )


# --------------------------------------------------------------------------- #
# Der Responses-Strom, der ausgelieferte Standardweg gegen LM Studio.
#
# Englischprobe 2026-09-27: jede Rundendatei zeigte "### Modell ? (Route:
# qwen3.8-27b-b)". _post_responses_stream_buffered gab die Antwort zurueck,
# ohne das Modell zu pruefen. Die Pruefung des gemeinsamen Stromlesers sah
# nur das erste Ereignis, und dort steht das Modell in ``response``, nicht
# oben. Die Ereignisse folgen dem Format des Responses-Stroms von LM Studio
# (response.created, output_item, output_text.done, response.completed).
# --------------------------------------------------------------------------- #
def _strom(antwortmodell: str) -> list[dict]:
    antwort = {
        "id": "resp_1",
        "object": "response",
        "status": "in_progress",
        "model": antwortmodell,
        "output": [],
    }
    fertig = {
        **antwort,
        "status": "completed",
        "output": [{
            "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": "Antwort"}],
        }],
    }
    return [
        {"type": "response.created", "sequence_number": 0, "response": antwort},
        {"type": "response.in_progress", "sequence_number": 1, "response": antwort},
        {"type": "response.output_item.added", "sequence_number": 2, "output_index": 0,
         "item": {"id": "msg_1", "type": "message", "role": "assistant", "content": []}},
        {"type": "response.output_text.done", "sequence_number": 3, "output_index": 0,
         "content_index": 0, "item_id": "msg_1", "text": "Antwort"},
        {"type": "response.completed", "sequence_number": 4, "response": fertig},
    ]


def _lies(ereignisse: list[dict], angefordert: str, gelesen: list[dict]) -> dict:
    import asyncio
    from unittest.mock import patch

    from candyconc.services import llm_client

    async def strom(*_args, **_kwargs):
        for ereignis in ereignisse:
            gelesen.append(ereignis)
            yield ereignis

    async def lauf() -> dict:
        with patch.object(llm_client, "_stream_json_with_retry", strom):
            return await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {"model": angefordert, "stream": True},
                timeout=None,
                headers=None,
            )

    return asyncio.run(lauf())


class TestResponsesStrom:
    def test_substitution_im_strom_wirft_hart_und_frueh(self):
        # Die Klasse zur Laufzeit: andere Testdateien laden llm_client neu.
        from candyconc.services import llm_client

        gelesen: list[dict] = []
        with pytest.raises(llm_client.LLMRequestError) as fehler:
            _lies(_strom("qwen3.8-flash-next"), "qwen3.8-27b-b", gelesen)
        assert fehler.value.kind is llm_client.LLMErrorKind.INVALID_RESPONSE
        assert "qwen3.8-flash-next" in str(fehler.value)
        # Am ersten Ereignis, nicht erst nach dem ganzen Lauf.
        assert [e["type"] for e in gelesen] == ["response.created"]

    def test_das_antwortende_modell_steht_in_der_rundendatei(self):
        from candyconc.candyconc_copilot.session_compaction import runde_lesbar
        from candyconc.services import llm_client

        ergebnis = _lies(_strom("qwen3.8-27b-b@q4_k_m"), "qwen3.8-27b-b", [])
        antwort = llm_client._attach_response_meta(
            llm_client._wrap_response("http://127.0.0.1:1234/v1/responses", ergebnis),
            llm_client._LLMRoute(endpoint="http://127.0.0.1:1234/v1/responses", model="qwen3.8-27b-b"),
        )
        assert antwort["model"] == "qwen3.8-27b-b@q4_k_m"
        text = runde_lesbar(nr=1, stufe="Antwort", messages=[], tools=[], antwort=antwort, dauer=1.0)
        assert "### Modell\nqwen3.8-27b-b@q4_k_m (Route: qwen3.8-27b-b)" in text

    def test_ein_strom_ohne_modellangabe_geht_durch(self):
        ereignisse = _strom("qwen3.8-27b-b")
        for ereignis in ereignisse:
            if "response" in ereignis:
                ereignis["response"] = {k: v for k, v in ereignis["response"].items() if k != "model"}
        ergebnis = _lies(ereignisse, "qwen3.8-27b-b", [])
        assert ergebnis["status"] == "completed"
