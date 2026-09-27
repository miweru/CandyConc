"""Drafting and synthesis run in the answer stage rather than the tool stage."""

import asyncio
import json

from candyconc.candyconc_copilot.deutung_abgeben import (
    DEUTUNG_ABGEBEN_TOOL,
    deutung_abgeben_tool,
)
from tests.ai._real_copilot import make_orchestrator

FRAGE = "Wie oft kommt 'und' vor? Sag mir bitte auch, wie du das einordnest."
_ZAEHLUNG = {
    "status": "success", "total": 797, "query": "und", "mode": "plain",
    "partial": False, "corpus_tokens": 55550, "per_million": 14347.4,
}


def _aufruf(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _turn(monkeypatch, tmp_path, *, abgabe, deutungspfad="1"):
    """Ein Turn: Runde 1 zaehlt (und gibt ab), danach schreibt das Modell."""
    monkeypatch.setenv("CANDYCONC_DEUTUNGSPFAD", deutungspfad)
    monkeypatch.setenv("CANDYCONC_ZWISCHENSTAENDE_DIR", str(tmp_path))
    aufrufe = []
    werkzeugrunden = {"n": 0}

    async def _modell(messages, tools, **kw):
        schema = kw.get("json_schema")
        namen = [t.get("function", {}).get("name") for t in (tools or [])]
        aufrufe.append({"stufe": orch._aktuelle_stufe, "werkzeuge": namen,
                        "schema": (schema or {}).get("name")})
        if schema is not None:
            inhalt = json.dumps({"response_requirements": []})
            return {"choices": [{"message": {"role": "assistant", "content": inhalt},
                                 "finish_reason": "stop"}]}
        if namen and werkzeugrunden["n"] == 0:
            werkzeugrunden["n"] += 1
            rufe = [_aufruf("c1", "query_count", {"query": "und"})]
            if abgabe:
                rufe.append(_aufruf("c2", "deutung_abgeben", {
                    "beantwortet": "Die Rate von und.",
                    "belege": ["E_query_count_1"], "offen": ""}))
            return {"choices": [{"message": {"role": "assistant", "tool_calls": rufe},
                                 "finish_reason": "tool_calls"}]}
        text = "Die Wortform kommt 797 {{ev:E_query_count_1.total}} mal vor. Deutung: haeufig."
        return {"choices": [{"message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}]}

    async def _werkzeug(aufruf, _token=None):
        name = aufruf["function"]["name"]
        if name == "deutung_abgeben":
            return deutung_abgeben_tool(**json.loads(aufruf["function"]["arguments"]))
        return dict(_ZAEHLUNG)

    werkzeuge = [{"type": "function",
                  "function": {"name": "query_count", "parameters": {"type": "object"}}},
                 DEUTUNG_ABGEBEN_TOOL]
    orch = make_orchestrator(werkzeuge, _modell, _werkzeug)
    orch._tool_runtime_info.update({
        "query_count": {"read_only": True, "concurrency_safe": True},
        "deutung_abgeben": {"read_only": True, "concurrency_safe": True},
    })
    ereignisse = []
    orch._emit_output = lambda _bus, ereignis: ereignisse.append(ereignis)
    asyncio.run(orch.run_async(FRAGE))
    stufen = [e.get("stage") for e in ereignisse if e.get("event") == "copilot.status"]
    rundendateien = {p.name: p.read_text(encoding="utf-8")
                     for p in tmp_path.rglob("runde_*.txt")}
    return aufrufe, stufen, rundendateien


def _schreibende(aufrufe):
    """Die Aufrufe, die Text schreiben: ohne Werkzeuge, ohne Schema."""
    return [a for a in aufrufe if not a["werkzeuge"] and a["schema"] is None]


def test_nach_der_abgabe_laufen_entwurf_und_synthese_in_der_stufe_antwort(
        monkeypatch, tmp_path):
    aufrufe, stufen, dateien = _turn(monkeypatch, tmp_path, abgabe=True)
    schreibend = _schreibende(aufrufe)
    assert len(schreibend) == 2, aufrufe  # Entwurf und Synthese
    assert [a["stufe"] for a in schreibend] == ["Antwort", "Antwort"], aufrufe
    # Gegenprobe: die Runde mit Werkzeugen bleibt, was sie war.
    assert all(a["stufe"] != "Antwort" for a in aufrufe if a["werkzeuge"]), aufrufe
    # Die Oberflaeche sieht die Stufe, nach den Werkzeugen.
    assert "Antwort" in stufen and stufen.index("Antwort") > stufen.index("Werkzeuge"), stufen
    # Und die Rundendatei widerspricht sich nicht mehr.
    leer = [text.splitlines()[0] for text in dateien.values()
            if "## Angebotene Werkzeuge (0)" in text]
    assert leer and all("Stufe: Antwort" in kopf for kopf in leer), leer


def test_ohne_abgabe_laeuft_die_synthese_in_der_stufe_antwort(monkeypatch, tmp_path):
    aufrufe, stufen, _dateien = _turn(monkeypatch, tmp_path, abgabe=False)
    mit_werkzeugen = [a for a in aufrufe if a["werkzeuge"]]
    schreibend = _schreibende(aufrufe)
    # Der Entwurf entsteht in einer Werkzeugrunde, dort gilt Werkzeuge weiter.
    assert mit_werkzeugen[-1]["stufe"] == "Werkzeuge", aufrufe
    assert [a["stufe"] for a in schreibend] == ["Antwort"], aufrufe
    assert stufen[-1] == "Antwort", stufen


def test_der_pruefpfad_endet_weiter_in_der_stufe_antwort(monkeypatch, tmp_path):
    """Ohne Deutungspfad folgt dem Entwurf die Verifikation.

    Der Entwurf nach der Abgabe schreibt ohne Werkzeuge und laeuft deshalb
    ebenfalls in Antwort. Der Strom fuer die Oberflaeche bleibt geschlossen:
    Verifikation folgt, und die letzte Stufe ist Antwort.
    """
    aufrufe, stufen, _dateien = _turn(monkeypatch, tmp_path, abgabe=True, deutungspfad="0")
    assert [a["stufe"] for a in _schreibende(aufrufe)] == ["Antwort"], aufrufe
    assert "Verifikation" in stufen and stufen[-1] == "Antwort", stufen
