# -*- coding: utf-8 -*-
"""Der leere Modell-Output ist ein Ausfall, keine Antwort.

Gelesen am Lauf 4, Runde 1 (2026-09-18, runde_01_Vorlauf.txt): LM Studio
lieferte nach 373 s Denken content LEER und tool_calls: [] MIT Schluessel
bei finish_reason length. Der Schluessel-Test im Orchestrator pruefte
Praesenz, nicht Wahrheit; der Fall lief durch alle Wachen bis zum stillen
Weiteraufruf mit leerer Assistant-Nachricht (runde_02, [3] assistant,
ohne Notiz, ohne Ereignis). Diese Entscheidung fasst die drei Erscheinungen
derselben Stoerung zusammen — stop, length, tool_calls mit leerer Liste.
Der stop-Fall war schon zuvor ein Retry MIT Evidenz (Diagnose lauf3) und
bleibt es; ohne Evidenz ist ein leerer Stop ein normales Ende (gepinnt in
tests/ai/test_empty_stop_is_retried.py).
"""

from __future__ import annotations

from typing import Any, List, Sequence

from candyconc.i18n import lt


def entscheidung(
    finish_reason: Any,
    inhalt: str,
    tool_calls: Sequence[Any],
    retries: int,
    hat_evidenz: bool,
    werkzeuge_angeboten: bool = False,
) -> str:
    """Return ``"normal"``, ``"wiederhole"`` or ``"stoerung"``.

    Allow one retry per incident. Content or a tool call resets ``retries``,
    so a later empty response starts a new incident. Two consecutive empty
    responses exhaust the retry. A length stop with grounding then finalizes
    deterministically from the turn evidence. Other exhausted cases are failures.
    """
    if (inhalt or "").strip() or tool_calls:
        return "normal"
    if finish_reason not in ("length", "stop", "tool_calls"):
        return "normal"
    # An empty stop while tools are offered is a failed generation.
    # Treating it as a decision to answer would close the model's investigation
    # and narrow the available tools before it had handed off.
    if retries < 1 and (finish_reason != "stop" or hat_evidenz or werkzeuge_angeboten):
        return "wiederhole"
    # A second empty response exhausts this incident's retry.
    # Keep the collected evidence and mark the result partial rather than
    # recording the unfinished investigation as a completed answer.
    if finish_reason == "stop" and not werkzeuge_angeboten:
        return "normal"
    return "stoerung"


#: Der Hinweis fuer den einen Retry. Ein Satz, denn er geht an das Modell.
HINWEIS = lt("Leere Modellantwort: einmal wiederholt.", "Empty model reply: repeated once.")
