"""H11.4: Reasoning-Staerke wird als Prompt-Text gesteuert, nie als Payload-Feld.

Gemessener Anlass (LM Studio + Qwen3.8-27B-GGUF, 2026-08-15):

    [qwen3.8-27b] No valid custom reasoning fields found in model
    '...Qwen3.8-27B-Q4_K_S.gguf'. Reasoning setting 'low' cannot be
    converted to any custom KVs.
    [qwen3.8-27b] Error: Channel Error

Sowohl das Top-Level-Feld ``reasoning_effort`` als auch
``chat_template_kwargs`` toeten den Turn. Diese Tests halten beide Felder
dauerhaft aus dem Payload heraus und pruefen den offiziellen Wortlaut der
Steuerzeile aus ``chat_template.jinja``.
"""

from __future__ import annotations

import pytest

from candyconc.services import llm_client


VERBOTENE_FELDER = ("reasoning_effort", "chat_template_kwargs", "reasoning")

MESSAGES = [
    {"role": "system", "content": "Du bist ein Korpuslinguistik-Assistent."},
    {"role": "user", "content": "Wie haeufig ist 'Frau'?"},
]


@pytest.fixture()
def effort(monkeypatch):
    def _set(value):
        monkeypatch.setattr(
            llm_client, "get_config", lambda key, *a, **k: (
                value if key == "COPILOT_REASONING_EFFORT" else None
            )
        )
    return _set


@pytest.mark.parametrize("wert", ["low", "medium", "high", "xhigh"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:1234/v1/chat/completions",
        "http://127.0.0.1:1234/v1/responses",
    ],
)
def test_payload_traegt_kein_reasoning_feld(effort, wert, endpoint):
    effort(wert)
    payload = llm_client._build_payload(
        endpoint=endpoint,
        model="qwen3.8-27b",
        messages=MESSAGES,
        tools=[],
        tool_choice=None,
        stream=False,
        seed=None,
        temperature=0.2,
    )
    for feld in VERBOTENE_FELDER:
        assert feld not in payload, (
            f"{feld} im Payload — LM Studio antwortet darauf mit "
            "'Channel Error' und der Turn stirbt als Engine-Ausfall."
        )


def test_low_injiziert_offiziellen_wortlaut(effort):
    effort("low")
    out = llm_client._apply_reasoning_steering(MESSAGES, "qwen3.8-27b")
    assert out[0]["role"] == "system"
    assert (
        "Reasoning effort is set to low. Keep thinking brief and focused "
        "and move directly to the conclusion." in out[0]["content"]
    )
    assert out[1] == MESSAGES[1]


def test_medium_injiziert_nichts(effort):
    """Das offizielle Template haengt bei medium keine Zeile an."""
    effort("medium")
    assert llm_client._apply_reasoning_steering(MESSAGES, "qwen3.8-27b") == MESSAGES


def test_xhigh_injiziert_gruendlichkeitszeile(effort):
    effort("xhigh")
    out = llm_client._apply_reasoning_steering(MESSAGES, "qwen3.8-27b")
    assert "Reasoning effort is set to xhigh." in out[0]["content"]


def test_fremdmodelle_bleiben_unberuehrt(effort):
    """Der Wortlaut stammt aus dem Qwen-Template und gilt nur dort."""
    effort("low")
    assert llm_client._apply_reasoning_steering(MESSAGES, "muse-glimmer") == MESSAGES


def test_steuerzeile_haengt_hinten_an(effort):
    """KV-Praefix bleibt byte-stabil: der statische Kern steht weiter vorn."""
    effort("low")
    out = llm_client._apply_reasoning_steering(MESSAGES, "qwen3.8-27b")
    assert out[0]["content"].startswith("Du bist ein Korpuslinguistik-Assistent.")


def test_zeile_wird_nicht_doppelt_angehaengt(effort):
    effort("low")
    einmal = llm_client._apply_reasoning_steering(MESSAGES, "qwen3.8-27b")
    zweimal = llm_client._apply_reasoning_steering(einmal, "qwen3.8-27b")
    assert zweimal[0]["content"].count("Reasoning effort is set to low") == 1
