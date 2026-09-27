"""Shared copilot sessions for streaming, continuation and WebSocket access.

Mutate the registry in place so all callers share its dictionary and lock.
The per-session run lock prevents two event loops from driving the same
orchestrator. Resolve authentication through the auth module at call time."""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict

from fastapi import HTTPException

from candyconc.config import get as get_config
from candyconc.entrypoints.errors import ApiError
from candyconc.i18n import lt

from . import auth

# Nur fuer die (String-)Annotationen der Session-Klasse/Registry — kein
# Laufzeit-Import des Orchestrators in diesem Leaf-Modul.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator


# Active orchestrators for Copilot control frame handling (action/clarification)
@dataclass(slots=True)
class _ActiveOrchestratorSession:
    orchestrator: "ReActOrchestrator"
    owner: str
    created_at: float
    last_seen: float
    # Hold this lock while driving the orchestrator. A state check alone lets
    # concurrent stream/continue requests drive it from separate event loops.
    # Non-blocking acquisition returns HTTP 409 to competing requests.
    run_lock: threading.Lock
    # Client-supplied opaque turn identifier. It is only a correlation key for
    # cancellation; the server-generated session id remains the authority.
    turn_id: str | None = None
    # Set by /copilot/cancel. A blocking LLM call cannot be force-killed here,
    # but the orchestrator observes this before every later tool/LLM boundary.
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    # Store completed work on the session so it survives a disconnected SSE
    # client. A returning client can retrieve the result.
    ergebnis: dict[str, Any] | None = None
    #: Gesetzt, sobald der Lauf fertig ist, egal ob mit Antwort oder Fehler.
    fertig: threading.Event = field(default_factory=threading.Event)
    #: Fortschritt fuer den Balken: (Schritt, erwartete Schritte, Text).
    #: Der Auftraggeber hat ihn ausdruecklich verlangt.
    fortschritt: dict[str, Any] = field(default_factory=dict)


_COPILOT_SESSION_TTL_SEC = float(
    get_config("CANDYCONC_COPILOT_SESSION_TTL_SEC", "1800")
)
_active_orchestrators: Dict[str, _ActiveOrchestratorSession] = {}
# Guards every read/mutate of _active_orchestrators — prune iterates the dict while
# popping, which races with concurrent register/get from streaming + control-frame
# endpoints (RuntimeError: dict changed size during iteration). RLock so the nested
# prune() calls inside register/get re-acquire safely.
_ACTIVE_ORCH_LOCK = threading.RLock()


def _prune_active_orchestrators(now: float | None = None) -> None:
    ttl = max(1.0, float(_COPILOT_SESSION_TTL_SEC))
    ts = time.monotonic() if now is None else float(now)
    with _ACTIVE_ORCH_LOCK:
        stale = [
            session_id
            for session_id, session in _active_orchestrators.items()
            if ts - float(session.last_seen) > ttl
        ]
        for session_id in stale:
            _active_orchestrators.pop(session_id, None)


def _register_active_orchestrator(
    session_id: str,
    orchestrator: "ReActOrchestrator",
    owner: str,
    *,
    turn_id: str | None = None,
) -> _ActiveOrchestratorSession:
    ts = time.monotonic()
    session = _ActiveOrchestratorSession(
        orchestrator=orchestrator,
        owner=str(owner),
        created_at=ts,
        last_seen=ts,
        run_lock=threading.Lock(),
        turn_id=turn_id,
    )
    with _ACTIVE_ORCH_LOCK:
        _prune_active_orchestrators(ts)
        _active_orchestrators[session_id] = session
    return session


def _lookup_active_session(
    session_id: str | None,
    turn_id: str | None,
) -> tuple[_ActiveOrchestratorSession, float]:
    if not session_id and not turn_id:
        raise HTTPException(status_code=400, detail="sessionId or turnId required")
    ts = time.monotonic()
    with _ACTIVE_ORCH_LOCK:
        _prune_active_orchestrators(ts)
        session = _active_orchestrators.get(session_id) if session_id else None
        if session is not None and turn_id and session.turn_id != turn_id:
            session = None
        if session is None and turn_id:
            session = next(
                (candidate for candidate in _active_orchestrators.values()
                 if candidate.turn_id == turn_id),
                None,
            )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session, ts


def _authorize_active_session(
    session: _ActiveOrchestratorSession,
    token: str | None,
    *,
    now: float,
) -> _ActiveOrchestratorSession:

    requester = auth.username_for_token(token)
    if requester is None:
        requester = "guest" if not auth.RBAC_ENABLED else None
    if requester is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if requester != session.owner and auth.role_for_token(token) != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    session.last_seen = now
    return session


def _get_active_session(
    session_id: str | None,
    token: str | None,
) -> _ActiveOrchestratorSession:
    session, ts = _lookup_active_session(session_id, None)
    session = _authorize_active_session(session, token, now=ts)
    if session.cancel_requested.is_set():
        raise ApiError(
            409, "copilot.turn_cancelled", lt("Copilot-Turn wurde abgebrochen", "Copilot turn was cancelled")
        )
    return session


def _cancel_active_session(
    session_id: str | None,
    turn_id: str | None,
    token: str | None,
) -> _ActiveOrchestratorSession:
    """Authenticate and cooperatively cancel one active Copilot turn."""
    session, ts = _lookup_active_session(session_id, turn_id)
    session = _authorize_active_session(session, token, now=ts)
    session.cancel_requested.set()
    request_cancel = getattr(session.orchestrator, "request_cancel", None)
    if callable(request_cancel):
        request_cancel()
    return session


def _cancel_running_turns_for_owner(
    owner: str,
    *,
    exclude_session_id: str | None = None,
) -> list[str]:
    """K1: Startet ein Owner einen NEUEN Turn, brennen alte nicht weiter.

    Cancelt kooperativ alle noch AKTIV laufenden Turns (run_lock gehalten)
    desselben Owners. Sessions, die nur auf Approval/Clarification warten
    (run_lock frei), bleiben unberuehrt, damit Genehmigungs-Fluesse nicht
    brechen. Liefert die Session-IDs der gecancelten Turns.
    """
    cancelled: list[str] = []
    with _ACTIVE_ORCH_LOCK:
        sessions = list(_active_orchestrators.items())
    for session_id, session in sessions:
        if exclude_session_id is not None and session_id == exclude_session_id:
            continue
        if session.owner != str(owner):
            continue
        if not session.run_lock.locked():
            continue
        session.cancel_requested.set()
        request_cancel = getattr(session.orchestrator, "request_cancel", None)
        if callable(request_cancel):
            request_cancel()
        cancelled.append(session_id)
    return cancelled


def lauf_abgekoppelt_starten(
    sitzung: "_ActiveOrchestratorSession",
    lauf: Any,
    *args: Any,
    **kwargs: Any,
) -> threading.Thread:
    """Start a turn in a session-owned thread that survives client disconnection.

The thread is not a daemon, so process shutdown does not discard it in
the middle of analysis. Store either its result or its exception on the
session so returning clients can retrieve a terminal state."""

    def _arbeiten() -> None:
        try:
            antwort = lauf(*args, **kwargs)
            sitzung.ergebnis = {"status": "fertig", "antwort": antwort}
        except BaseException as fehler:  # noqa: BLE001 - siehe Docstring
            sitzung.ergebnis = {
                "status": "fehler",
                "fehler": f"{type(fehler).__name__}: {fehler}",
            }
        finally:
            sitzung.fertig.set()

    faden = threading.Thread(
        target=_arbeiten, name="candyconc-copilot-turn", daemon=False
    )
    faden.start()
    return faden


def fortschritt_setzen(
    sitzung: "_ActiveOrchestratorSession",
    *,
    schritt: int,
    von: int,
    text: str = "",
) -> None:
    """Den Fortschritt fuer den Balken fortschreiben.

    Der Auftraggeber hat ihn ausdruecklich verlangt ("und er hat dann auch
    so ne progressbar"). Eine Textzeile allein sagt nicht, wie weit es
    noch ist.

    ``von`` ist die ERWARTETE Schrittzahl, keine Zusage. Sie waechst mit,
    wenn ein Turn mehr Schritte braucht als geplant: ein Balken, der bei
    100 Prozent stehenbleibt und weiterlaeuft, ist schlimmer als keiner.
    """
    schritt = max(0, int(schritt))
    von = max(schritt, int(von))
    sitzung.fortschritt = {
        "schritt": schritt,
        "von": von,
        "anteil": (schritt / von) if von else 0.0,
        "text": str(text or ""),
        "ts": int(time.time() * 1000),
    }


def fortschrittsanteil(gelaufen: int, budget: int) -> dict[str, Any] | None:
    """Der Anteil fuer den Balken, oder nichts.

    ``None`` heisst: kein Budget bekannt, also KEIN Balken. Das Frontend
    zeigt ohne Feld bewusst nichts, und das ist die richtige Haelfte der
    Wahl: ein Balken, der raet, ist schlimmer als eine Textzeile.

    Das Budget WAECHST mit, wenn ein Turn mehr Schritte braucht als
    geplant. Ein Balken, der bei hundert Prozent stehenbleibt und
    weiterlaeuft, ist schlimmer als keiner.

    Liegt in diesem Modul, weil ``fortschritt_setzen`` daneben steht und
    weil der Orchestrator an seinem Zeilendeckel sitzt. Der Deckel verlangt
    Zerlegung statt Anhebung, und diese Rechnung gehoert ohnehin zur
    Sitzung, nicht zur Turnschleife.
    """
    budget = int(budget or 0)
    if budget <= 0:
        return None
    gelaufen = max(0, int(gelaufen or 0))
    budget = max(budget, gelaufen)
    return {
        "schritt": gelaufen,
        "von": budget,
        "anteil": round(gelaufen / budget, 3),
    }

