"""Rollen-Normalisierung fuer Templates mit striktem Wechsel.

Live-Befund 2026-09-06 (mistral-small-4-119b, F4-Neumessung): Templates
mit "got system" und "must alternate user and assistant roles" brechen an
zweiten System-Rollen und aufeinanderfolgenden gleichen Rollen. Die
Normalisierung fasst beide Faelle zusammen.
"""

from candyconc.services.llm_client import _normalize_system_position


def rollen(ms):
    return [m["role"] for m in ms]


def test_system_hinter_dem_kopf_wird_user_mit_marker():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "frage"},
        {"role": "system", "content": "hinweis"},
    ]
    out, veraendert = _normalize_system_position(msgs)
    assert rollen(out) == ["system", "user"]
    assert "[Systemhinweis]" in out[1]["content"] and "hinweis" in out[1]["content"]
    assert veraendert


def test_aufeinanderfolgende_gleiche_rollen_werden_zusammengefuehrt():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    out, veraendert = _normalize_system_position(msgs)
    assert rollen(out) == ["system", "user"]
    assert out[1]["content"] == "a\n\nb"
    assert veraendert


def test_saubere_sequenz_bleibt_unveraendert():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    out, veraendert = _normalize_system_position(msgs)
    assert rollen(out) == ["system", "user", "assistant"]
    assert not veraendert
