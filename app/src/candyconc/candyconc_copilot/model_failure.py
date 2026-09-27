# -*- coding: utf-8 -*-
"""Warten und Landen nach einer Modellstoerung (B16-Zerlegung).

Die beiden Methoden lesen ausschliesslich Instanzzustand und die
Turn-Bilanz — eine saubere Mixin-Grenze wie WacheEmitterMixin. Verhalten
byte-identisch: die Methodenkoerper sind unveraendert uebersiedelt.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from candyconc.services.llm_client import LLMErrorKind, LLMRequestError

from .session_compaction import turn_usage_snapshot

if TYPE_CHECKING:  # pragma: no cover
    from .orchestrator import _RunTurnState

logger = logging.getLogger(__name__)


class ModellstoerungMixin:
    """Nachfrist vor demselben Modell und die ehrliche Notlandung."""

    async def _ra_warte_auf_modell(self, turn_state: "_RunTurnState") -> bool:
        """Wartet nach einer Modellstoerung auf DASSELBE Modell, laedt nichts.

        Nachfrist ist die Restzeit des Turns; ohne Turn-Budget ohne Grenze.
        """
        from candyconc.services import llm_client as _lc

        rest: float | None = None
        if turn_state.max_time and turn_state.max_time > 0:
            rest = max(0.0, float(turn_state.max_time)
                       - (time.perf_counter() - float(turn_state.started_at)))
        return await self._ra_await_with_cancellation(_lc.warte_auf_modell(
            str(_lc.get_config("COPILOT_ENDPOINT") or ""),
            str(self._last_llm_model or _lc.get_config("COPILOT_MODEL") or ""),
            timeout=rest,
        ))

    def _ra_lande_nach_modellstoerung(
        self, copilot_event_bus: Any, normalized_question: str,
        turn_state: "_RunTurnState", start_time: float, exc: LLMRequestError,
        *, stream: bool,
    ) -> str:
        """CLAUDE.md, Zeitlimits Punkt 3: Teilantwort, Evidenz und Bilanz
        bleiben. Bis Runde 5 warf der Turn bis zum Server und hinterliess
        status None, calls None, 41 mal."""
        logger.warning("Modellstörung nach erschöpftem Warten: %s", exc)
        self._emit_output(copilot_event_bus,
                          {"event": "copilot.error", "error": str(exc)})
        text = None
        try:
            text = self.build_salvage_markdown()
        except Exception:
            logger.exception("build_salvage_markdown nach Modellstörung")
        if not text:
            # Empty or unreadable output still comes from a reachable model.
            # Only the remaining failure class represents an unreachable service.
            grund = ("Das Modell lieferte auch nach einer Wiederholung keine "
                     "verwertbare Ausgabe. "
                     if getattr(exc, "kind", None) == LLMErrorKind.INVALID_RESPONSE
                     else "Die Modell-Engine blieb nach wiederholtem Warten unerreichbar. ")
            text = self._ra_build_fail_closed_grounding_markdown(
                grund + "Die Antwort wurde deterministisch aus der bis dahin "
                "gesammelten Evidenz gebildet.")
        from .orchestrator import State  # faul: State lebt im Orchestrator
        self.state = State.FINISHED
        self._last_turn_usage = turn_usage_snapshot(
            turn_state, start_time=start_time,
            recipe_id=turn_state.recipe_id or self._active_recipe_id,
            session=self.session)
        return self._ra_finish_turn(copilot_event_bus, normalized_question,
                                    text, stream_emit=stream)
