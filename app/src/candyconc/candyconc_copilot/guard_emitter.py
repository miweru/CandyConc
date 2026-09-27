"""Ereignis-Emitter der Reakt-Wache als Mixin (B16-Zerlegung, Runde 4).

Die drei emit-Methoden haben den Orchestrator an die 7800er-LOC-Marke
getrieben; sie lesen ausschliesslich Instanzzustand und geben SSE-Events
aus — eine saubere Mixin-Grenze. Verhalten byte-identisch: die Methoden-
koerper sind unveraendert uebersiedelt.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from candyconc.answer_language import text_value
from .recipe_runtime import kontrollrahmen_bewacht, recipe_routing_annotation


class WacheEmitterMixin:
    """copilot.recovery / copilot.research / copilot.grounding emittieren."""

    def _ra_emit_recovery(
        self,
        copilot_event_bus: Any,
        question: str,
        kind: str,
        message: str,
        *,
        error: LLMRequestError | None = None,
    ) -> None:
        route = getattr(error, "route", None) if error else None
        model = getattr(error, "model", None) if error else None
        # A LocalizedText message is written in the answer language of the
        # turn (answer_language.py), German turns keep their German text.
        message = text_value(message)
        # Modelltext: reference_repair traegt ein +-48-Zeichen-Fenster aus
        # dem ENTWURF, samt erfundenem Zitat, in Chat und Projektprotokoll.
        message = kontrollrahmen_bewacht(
            {"note": message}, list(self._turn_evidence_items or ()), frage=getattr(self, "_turn_frage", ""))["note"]
        recovery_payload = {
            "kind": kind,
            "message": message,
            "model": model,
            "route": route,
            "retryable": bool(getattr(error, "retryable", False)) if error else False,
            "ts": int(time.time() * 1000),
        }
        rendered = self._compact_runtime_text(
            " | ".join(part for part in (kind, route or "", model or "", message) if part),
            limit=220,
        )
        if rendered:
            self._recent_recoveries.append(rendered)
            self._recent_recoveries = self._recent_recoveries[-8:]
        if route:
            self._last_llm_route = str(route)
        if model:
            self._last_llm_model = str(model)
        self._ra_refresh_session_state(question)
        event = {"event": "copilot.recovery", "recovery": recovery_payload}
        self._emit_output(copilot_event_bus, event)
        if self.project:
            self.project.add_ai_output(json.dumps(event, ensure_ascii=False))
        if self.observability:
            self.observability.record(
                self.session.session_id,
                "copilot.recovery",
                status=kind,
            )

    def _ra_emit_research_event(
        self,
        copilot_event_bus: Any,
        run: Dict[str, Any],
        phase: str,
        **payload: Any,
    ) -> None:
        event = {
            "event": "copilot.research",
            "researchId": str(run.get("id", "") or ""),
            "phase": phase,
            "query": str(run.get("query", "") or ""),
            "ts": int(time.time() * 1000),
        }
        for key, value in payload.items():
            if value not in (None, "", [], {}):
                event[key] = value
        self._emit_output(copilot_event_bus, event)
        if self.project:
            self.project.add_ai_output(json.dumps(event, ensure_ascii=False))
        if self.observability:
            self.observability.record(
                self.session.session_id,
                f"research.{phase}",
                status=str(run.get("status", phase) or phase),
            )

    def _ra_emit_grounding_event(
        self,
        copilot_event_bus: Any,
        verdict: str,
        *,
        analysis_family: str,
        rejected_claim_count: int = 0,
        evidence_gaps: List[str] | None = None,
    ) -> None:
        # Severity-Durchleitung (R2): beratende Befunde aus
        # validate_answer_envelope blockieren nichts, sie erscheinen als
        # annotations-Liste im Event (dokumentiert in docs/reference/http-api.md).
        raw_advisories = (self._last_grounding_verdict or {}).get("advisories")
        annotations: List[Dict[str, str]] = []
        if isinstance(raw_advisories, dict):
            annotations = [
                {"claim_id": str(claim_id), "note": str(note)}
                for claim_id, notes in raw_advisories.items()
                for note in (notes or [])
                if str(note or "").strip()
            ]
        routing_note = recipe_routing_annotation(self._turn_recipe_routing)
        if routing_note:  # H9/C1: Routing-Stufe sichtbar fuer Evals.
            annotations.append(routing_note)
        payload = {
            "analysis_family": analysis_family,
            "verdict": verdict,
            "rejected_claim_count": rejected_claim_count,
            "annotations": annotations,
            "route": self._last_llm_route,
            "model": self._last_llm_model,
            "ts": int(time.time() * 1000),
        }
        event = {"event": "copilot.grounding", "grounding": payload}
        self._emit_output(copilot_event_bus, event)
        if self.project:
            self.project.add_ai_output(json.dumps(event, ensure_ascii=False))
        if self.observability:
            self.observability.record(
                self.session.session_id,
                "copilot.grounding",
                status=verdict,
            )
        if evidence_gaps:
            gap_event = {
                "event": "copilot.evidence_gap",
                "analysis_family": analysis_family,
                "gaps": list(evidence_gaps[:6]),
                "route": self._last_llm_route,
                "model": self._last_llm_model,
                "ts": int(time.time() * 1000),
            }
            self._emit_output(copilot_event_bus, gap_event)
            if self.project:
                self.project.add_ai_output(json.dumps(gap_event, ensure_ascii=False))


