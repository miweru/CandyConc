"""Die Ausnahmeklassen der Copilot-Werkzeuge, in EINEM Modul.

Sie standen bis zum 2026-08-29 in ``tool_wrappers``. Das ist eine Falle,
und sie ist im Projekt schon zweimal zugeschnappt: ``tests/conftest.py``
legt fuer ``tool_wrappers`` eine Attrappe in ``sys.modules``, und Tests
laden das echte Modul per importlib NEU. Dabei entsteht eine zweite
Klasse mit demselben Namen, und ein ``except ToolInputError`` faengt die
geworfene Ausnahme nicht, weil es eine andere Klasse ist.

Beim ersten Mal meldete ein Test daraufhin, eine Wache sei nicht
erreicht worden, obwohl sie zuschlug. Beim zweiten Mal, bei der
Auslagerung von ``pruefe_metadatenfelder``, dasselbe.

Hier definiert, bleiben die Klassen ueber jeden Ladepfad hinweg dieselben
Objekte: ``tool_wrappers`` importiert sie und exportiert sie weiter, ein
Neuladen bindet dasselbe Klassenobjekt.
"""

from __future__ import annotations


class UnknownResourceError(RuntimeError):
    """A copilot tool was asked for a corpus/docset that is unknown or not loaded.

    COPILOT-3: this is a *bad request* (the LLM named a corpus/docset that does
    not exist), not an internal failure. Subclassing ``RuntimeError`` keeps every
    existing ``except RuntimeError`` / caller working unchanged; the only consumer
    that treats it specially is the MCP boundary (``services.mcp_server.call_tool``),
    which maps it to HTTP 404 instead of a misleading 500. Genuine engine/index
    faults stay plain ``RuntimeError`` and keep their 500.
    """


class ToolInputError(ValueError):
    """A copilot tool was called with invalid / incomplete arguments.

    COPILOT-KEYNESS-INCOMPLETE-500: the LLM supplied only one half of a required
    pair (e.g. ``target_corpus`` without ``reference_corpus``). That is a *bad
    request*, not an internal fault. The MCP boundary
    (``services.mcp_server.call_tool``) maps it to HTTP 400 instead of a
    misleading 500. Subclassing ``ValueError`` keeps it distinct from the genuine
    engine ``RuntimeError`` faults that legitimately stay 500.
    """
