"""P2 (Runde 4): die Notkomposition nach Engine-Tod in der Finalisierung
landet ehrlich als partial_on_engine_error, nicht als clean completed.

Messung r4a-naht-pds/r4b-praesidiumsprofil: 4 von 6 completed-Antworten
waren deterministische Notkompositionen nach Finalisierungs-Crash — der
done-Status log."completed", obwohl der Kern (die Synthese) an der
Engine starb.
"""

from candyconc.services.backend.routes.copilot import _copilot_terminal_events


def _events(reply=None, error_text=None, salvage_text=None, timed_out=False):
    return _copilot_terminal_events(
        session_id="s",
        reply=reply,
        salvage_text=salvage_text,
        timed_out=timed_out,
        error_text=error_text,
        usage_report={},
    )


def test_notkomposition_mit_engine_fehler_landet_partial():
    events = _events(reply="Deterministische Notkomposition.",
                     error_text="Context size exceeded")
    done = dict(next(d for name, d in events if name == "copilot.done"))
    assert done["status"] == "partial"
    assert done["partial"] is True
    assert done["error"] == "Context size exceeded"
    gruendung = dict(
        next(d for name, d in events if name == "copilot.grounding")
    )["grounding"]
    assert gruendung["verdict"] == "partial_on_engine_error"


def test_sauberer_abschluss_bleibt_completed():
    events = _events(reply="Vollständige Antwort mit Deutung.")
    done = dict(next(d for name, d in events if name == "copilot.done"))
    assert done["status"] == "completed"
    assert all(name != "copilot.grounding" for name, _ in events)
