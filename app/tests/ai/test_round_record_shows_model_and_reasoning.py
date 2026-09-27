"""Round records identify the responding model and its reasoning output."""

from candyconc.candyconc_copilot.session_compaction import runde_lesbar


def _antwort(**nachricht):
    return {
        "model": "qwen3.8-27b-b",
        "usage": {"prompt_tokens": 41000, "completion_tokens": 14255},
        "choices": [{"message": nachricht, "finish_reason": "length"}],
    }


def test_leere_runde_zeigt_ihr_denken_und_das_modell():
    text = runde_lesbar(
        nr=8, stufe="Werkzeuge", messages=[{"role": "user", "content": "Frage"}],
        tools=[], antwort=_antwort(content="", reasoning_content="Ich zaehle erst die Register."),
        dauer=217.3,
    )
    assert "### content\nLEER" in text
    assert "### finish_reason\nlength" in text
    assert "### Modell\nqwen3.8-27b-b" in text
    assert '"completion_tokens": 14255' in text
    assert "### Denken\nIch zaehle erst die Register." in text


def test_ohne_denken_steht_das_auch_da():
    text = runde_lesbar(
        nr=1, stufe="Vorlauf", messages=[], tools=[],
        antwort=_antwort(content="Antwort"), dauer=1.0,
    )
    assert "### Denken\nnicht geliefert" in text
