import json

from candyconc.services.llm_client import _build_payload
from tests.ai._real_copilot import make_orchestrator


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_count",
            "description": "Count corpus hits",
            "parameters": {"type": "object", "properties": {"term": {"type": "string"}}},
        },
    }
]


def test_responses_payload_uses_native_function_call_output_continuation():
    messages = [
        {"role": "system", "content": "Du bist ein Korpusassistent."},
        {"role": "user", "content": "Wie oft kommt Klima vor?"},
        {
            "role": "assistant",
            "_cc_response_id": "resp_123",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "query_count", "arguments": "{\"term\":\"Klima\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"count\":4}"},
    ]

    payload = _build_payload(
        "http://127.0.0.1:1234/v1/responses",
        "qwen",
        messages,
        TOOLS,
        stream=False,
    )

    assert payload["previous_response_id"] == "resp_123"
    assert payload["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "{\"count\":4}",
        }
    ]
    assert "[Tool Result" not in json.dumps(payload, ensure_ascii=False)
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "query_count"
    # Nutzervorgabe: KEIN Ausgabe-Budget auf LLM-Calls. Die Vorfassung
    # dieser Zeile hielt den Default 16384 fest und damit einen Deckel an
    # JEDEM Aufruf. Der Ausschalter existierte, nur nutzte ihn der Default
    # nicht. Geprueft wird jetzt die ABWESENHEIT des Feldes.
    assert "max_output_tokens" not in payload


def test_responses_payload_honours_required_tool_choice():
    payload = _build_payload(
        "http://127.0.0.1:1234/v1/responses",
        "gemma",
        [{"role": "user", "content": "Erhebe die fehlende Evidenz."}],
        TOOLS,
        stream=False,
        tool_choice="required",
    )

    assert payload["tool_choice"] == "required"


def test_chat_payload_honours_required_tool_choice():
    payload = _build_payload(
        "http://127.0.0.1:1234/v1/chat/completions",
        "gemma",
        [{"role": "user", "content": "Erhebe die fehlende Evidenz."}],
        TOOLS,
        stream=False,
        tool_choice="required",
    )

    assert payload["tool_choice"] == "required"
    assert "max_tokens" not in payload


def test_responses_payload_falls_back_to_text_context_without_response_id():
    messages = [
        {"role": "user", "content": "Wie oft kommt Klima vor?"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "query_count", "arguments": "{\"term\":\"Klima\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"count\":4}"},
    ]

    payload = _build_payload(
        "http://127.0.0.1:1234/v1/responses",
        "qwen",
        messages,
        TOOLS,
        stream=False,
    )

    assert "previous_response_id" not in payload
    assert isinstance(payload["input"], str)
    assert "[Tool Result call_1]" in payload["input"]


def test_responses_payload_falls_back_when_adapter_returns_chat_completion_id():
    messages = [
        {"role": "user", "content": "Wie oft kommt Klima vor?"},
        {
            "role": "assistant",
            "_cc_response_id": "chatcmpl-local-adapter",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "query_count", "arguments": "{\"term\":\"Klima\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"count\":4}"},
    ]

    payload = _build_payload(
        "http://127.0.0.1:1234/v1/responses",
        "gemma",
        messages,
        TOOLS,
        stream=False,
    )

    assert "previous_response_id" not in payload
    assert isinstance(payload["input"], str)
    assert "[Tool Result call_1]" in payload["input"]


def test_responses_payload_does_not_reuse_consumed_previous_response_id():
    messages = [
        {"role": "user", "content": "Wie oft kommt Klima vor?"},
        {
            "role": "assistant",
            "_cc_response_id": "resp_123",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "query_count", "arguments": "{\"term\":\"Klima\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"count\":4}"},
        {"role": "assistant", "content": "Klima kommt 4-mal vor."},
        {"role": "user", "content": "Und Demokratie?"},
    ]

    payload = _build_payload(
        "http://127.0.0.1:1234/v1/responses",
        "qwen",
        messages,
        TOOLS,
        stream=False,
    )

    assert "previous_response_id" not in payload
    assert isinstance(payload["input"], str)
    assert "Und Demokratie?" in payload["input"]


def test_orchestrator_preserves_responses_id_for_next_tool_turn():
    seen_messages = []

    async def call_llm(messages, tools, **kwargs):
        if messages and str(messages[0].get("content", "")).startswith(
            "Ordne die folgende korpuslinguistische Nutzerfrage"
        ):
            # H9/C1 Router-Klassifikator (Stufe 2): 'frei' antworten, ohne
            # die gescriptete Nachrichtenfolge zu verbrauchen.
            return {"choices": [{"message": {"content": "frei"}}]}
        seen_messages.append([dict(message) for message in messages])
        if len(seen_messages) == 1:
            return {
                "id": "resp_123",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "query_count", "arguments": "{\"term\":\"Klima\"}"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        return {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}

    def dispatch(call, token=None):
        return {"count": 4, "term": "Klima"}

    orch = make_orchestrator(TOOLS, call_llm, dispatch)
    # This test isolates Responses continuation IDs. Query counts now correctly
    # activate the separate grounding preflight, which is covered elsewhere.
    orch._ra_requires_grounding_contract = lambda: False

    result = orch.run("Wie oft kommt Klima vor?")

    assert result == "done"
    assert getattr(orch.state, "value", orch.state) == "finished"
    assert len(seen_messages) == 2
    assert any(
        message.get("role") == "assistant"
        and message.get("_cc_response_id") == "resp_123"
        and message.get("tool_calls")
        for message in seen_messages[1]
    )


def test_kein_ausgabebudget_per_default_aber_bewusst_setzbar(monkeypatch):
    """Nutzervorgabe, mehrfach ausgesprochen: KEIN max_tokens auf LLM-Calls.

    Reasoning-Modelle liefern unter einem Deckel leeren Content, weil das
    Budget im Reasoning aufgeht. Der Ausschalter (Wert <= 0) war seit jeher
    da, der Default stand aber auf 16384 und hing damit an JEDEM Aufruf.

    Der Mechanismus bleibt: ein ausdruecklich gesetzter positiver Wert
    wirkt weiter. Ohne diese zweite Haelfte waere der Test nur die halbe
    Wahrheit, denn eine tote Funktion bestuende ihn genauso.
    """
    from candyconc.services import llm_client as lc

    for pfad, feld in (
        ("http://127.0.0.1:1234/v1/responses", "max_output_tokens"),
        ("http://127.0.0.1:1234/v1/chat/completions", "max_tokens"),
    ):
        payload = _build_payload(
            pfad, "qwen",
            [{"role": "user", "content": "Wie oft kommt Klima vor?"}],
            TOOLS, stream=False,
        )
        assert feld not in payload, f"{feld} steht trotz Default 0 im Payload"

    assert lc._get_max_output_tokens() is None

    monkeypatch.setattr(
        lc, "get_config",
        lambda name, default=None: "4096"
        if name == "COPILOT_MAX_OUTPUT_TOKENS" else default,
    )
    assert lc._get_max_output_tokens() == 4096
