"""Ein normal geschlossener Socket erzeugt keinen Traceback.

LIVE GESEHEN am 2026-08-31. Ein Nutzer bricht einen Kollokationsjob ab,
der Server sendet gerade die naechste Zeile, und im Protokoll steht ein
vierzigzeiliger ASGI-Traceback:

    websockets.exceptions.ConnectionClosedOK: received 1005
    (no status received [internal])

Fuer den Nutzer passiert nichts, der Job war abgebrochen. Der Schaden ist
das Protokoll: ein Traceback fuer einen erwarteten Vorgang deckt echte
Fehler zu, und genau danach sucht man, wenn etwas kaputt ist.

URSACHE. Beide Handler fangen ``WebSocketDisconnect`` von Starlette. Die
wird geworfen, wenn der ASGI-Server den Abbruch als EREIGNIS meldet.
Schliesst der Browser dagegen, waehrend der Server SENDET, kommt der
Abbruch aus der websockets-Bibliothek als ``ConnectionClosedOK``, und die
ist keine Unterklasse von ``WebSocketDisconnect``.
"""

from __future__ import annotations

import ast
import pathlib

_QUELLE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "candyconc" / "services" / "backend" / "routes" / "copilot_ws.py"
)


def test_die_bibliotheksklasse_ist_bekannt():
    from candyconc.services.backend.routes import copilot_ws

    namen = [k.__name__ for k in copilot_ws._ABBRUCH]
    assert "ConnectionClosed" in namen, namen


def test_ein_normaler_abbruch_ist_eine_unterklasse():
    """ConnectionClosedOK, was live auftrat, muss wirklich gefangen sein."""
    from websockets.exceptions import ConnectionClosedOK

    from candyconc.services.backend.routes import copilot_ws

    assert issubclass(ConnectionClosedOK, tuple(copilot_ws._ABBRUCH))


def test_beide_handler_fangen_ihn():
    """Eine Naht von zwei zu fassen waere ein verschobener Defekt.

    Geprueft werden die AUSNAHMEZWEIGE beider Websocket-Handler, nicht der
    Dateitext: ein Kommentar mit dem Klassennamen wuerde einen Texttest
    schon zufriedenstellen.
    """
    baum = ast.parse(_QUELLE.read_text(encoding="utf-8"))
    handler = [
        k for k in ast.walk(baum)
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
        and k.name in {"ws_faiss", "ws_analysis"}
    ]
    assert len(handler) == 2, [h.name for h in handler]
    for h in handler:
        gefangen = []
        for knoten in ast.walk(h):
            if isinstance(knoten, ast.ExceptHandler) and knoten.type is not None:
                gefangen.append(ast.dump(knoten.type))
        assert any("_ABBRUCH" in g for g in gefangen), (
            f"{h.name} faengt den Bibliotheksabbruch nicht: {gefangen}"
        )
