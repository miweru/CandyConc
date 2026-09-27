"""Die Verdichtung trennt kein Werkzeugergebnis von seinem Aufruf.

Muse-Lauf auf 8689dde5c3, Frage 15: Ein Modellzug rief zehn
Werkzeuge, der Rest des Verlaufs bestand nur aus ihren Ergebnissen. Der
Schnitt lief ans Ende und fiel auf das letzte Ergebnis zurueck, der Aufruf
wurde verdichtet, das Ergebnis blieb. OpenRouter lehnte den Verlauf mit
HTTP 400 ab („No function call found for function call output“).
"""

import unittest

from tests.ai._real_copilot import SessionManager, lm_summary_stub


def _zug_mit_aufrufen(n):
    ids = [f"call_{i}" for i in range(n)]
    zug = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "keyness", "arguments": "{}"}}
            for i in ids
        ],
    }
    return zug, [{"role": "tool", "tool_call_id": i, "content": "{}"} for i in ids]


def _verwaiste_ergebnisse(verlauf):
    bekannt = set()
    verwaist = []
    for m in verlauf:
        for tc in m.get("tool_calls") or []:
            bekannt.add(tc["id"])
        if m.get("role") == "tool" and m.get("tool_call_id") not in bekannt:
            verwaist.append(m["tool_call_id"])
    return verwaist


class TestVerdichtungTrenntKeinenAufruf(unittest.TestCase):
    def _verlauf(self, sm):
        sm.append({"role": "user", "content": "Frage"})
        for runde in range(2):
            zug, ergebnisse = _zug_mit_aufrufen(10)
            for i, e in enumerate(ergebnisse):
                e["tool_call_id"] = zug["tool_calls"][i]["id"] = f"r{runde}_{i}"
            sm.append(zug)
            for e in ergebnisse:
                sm.append(e)

    def test_force_compact_laesst_kein_ergebnis_ohne_aufruf(self):
        with lm_summary_stub():
            sm = SessionManager(max_messages=200)
            self._verlauf(sm)
            sm.force_compact(keep_last_messages=6)
        self.assertEqual(_verwaiste_ergebnisse(sm.history), [])

    def test_summarise_laesst_kein_ergebnis_ohne_aufruf(self):
        with lm_summary_stub():
            sm = SessionManager(max_messages=8)
            self._verlauf(sm)
            sm.summarise()
        self.assertEqual(_verwaiste_ergebnisse(sm.history), [])


if __name__ == "__main__":
    unittest.main()
