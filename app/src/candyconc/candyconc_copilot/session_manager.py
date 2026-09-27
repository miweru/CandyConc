from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING
from pathlib import Path
import tempfile
import uuid
import json
import time
import asyncio

from .memory_store import MemoryStore
from .session_compaction import session_max_messages, session_max_tokens

if TYPE_CHECKING:  # pragma: no cover - optional import for type hints
    from candyconc.project import Project


class SessionManager:
    """In-memory store for conversation history and tool outputs.

    The manager keeps the recent message history and collapses older
    turns into short summary notes so that the orchestrator can stay
    within the context window of the language model.
    """

    _STRUCTURED_NOTE_PREFIX = "CC_SESSION_SUMMARY "
    _MICROCOMPACT_STATUS = "compacted"
    _SUMMARY_FIELDS = (
        "user_goal",
        "active_question",
        "active_filters",
        "active_selection",
        "ui_focus",
        "open_clarification",
        "open_approval",
        "current_plan",
        "active_analysis_contract",
        # ``last_valid_tool_results`` steht hier BEWUSST NICHT. Das Fach
        # fuellt ausschliesslich orchestrator._recent_tool_results, und
        # zwar nur mit Eintraegen, die ok sind. Solange das Modell es
        # selbst setzen durfte, trug eine frei erfundene Zeile die
        # Ueberschrift "Letzte belastbare Tool-Ergebnisse", ohne dass ein
        # Werkzeug gelaufen war. Die vorige Reparatur schloss nur den
        # Zweig, in dem das Modell das FORMAT verfehlt -- das Etikett
        # wanderte damit auf den Pfad, den ein formattreues Modell gerade
        # nicht nimmt. Modelltext zu diesem Punkt landet in
        # ``modell_zusammenfassung``.
        "grounded_fact_notes",
        "evidence_gaps",
        "blocked_claims",
        "last_grounding_verdict",
        "research_contexts",
        "recent_research_findings",
        "background_tasks",
        "failed_attempts",
        "recent_recoveries",
        "last_llm_route",
        "next_step",
        "reason",
    )

    def __init__(
        self,
        max_messages: int | None = None,
        max_tokens: int | None = None,
        max_summary_messages: int = 4,
        max_search_messages: int = 3,
        *,
        session_id: str | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        # Die Vorgaben kommen aus der Naht in ``sitzungsverdichtung`` und
        # folgen dem Kontextfenster des Modells (seit 2026-09-26 nicht mehr
        # ``max_steps``). Sie werden HIER aufgeloest und nicht an
        # den vier Baustellen (__init__.py:191, orchestrator.py:869,
        # routes/copilot.py:357 und :482), damit keine fuenfte Baustelle
        # sie wieder verfehlen kann. Wer die Zahlen ausdruecklich uebergibt,
        # etwa eine Probe, behaelt sie unveraendert.
        self.max_messages = (
            session_max_messages() if max_messages is None else max_messages
        )
        self.max_tokens = (
            session_max_tokens() if max_tokens is None else max_tokens
        )
        self.max_summary_messages = max(1, max_summary_messages)
        self.max_search_messages = max(0, max_search_messages)
        self.session_id = session_id or uuid.uuid4().hex
        self.history: List[Dict[str, Any]] = []
        tmp_dir = Path(tempfile.gettempdir())
        default_store = tmp_dir / f"{self.session_id}.jsonl"
        self.memory = MemoryStore(path=db_path or default_store)
        self.summaries: List[str] = list(self.memory.notes)
        self._search_results: List[str] = []
        self._rehydration_state: Dict[str, Any] = {}
        #: Bilanz des Zusammenfassers seit dem Beginn des laufenden Turns.
        #: ``_lm_summary`` ist ein echter Modellaufruf, stand aber in keiner
        #: Bilanz, weil ``llm_calls_used`` nur die Aufrufe des Orchestrators
        #: zaehlt (orchestrator.py:4739). Ein Turn mit vier Verdichtungen
        #: meldete vier Modellaufrufe weniger, als er getan hatte.
        self.verdichtungs_aufrufe: int = 0
        self.verdichtungs_sekunden: float = 0.0
        #: Werkzeugzeilen, die ``microcompact`` in diesem Turn auf einen
        #: 220-Zeichen-Stummel umgeschrieben hat. Das ist die haertere
        #: Haelfte des Befunds und lief bisher ohne jede Spur: microcompact
        #: ruft KEIN Modell, erhoeht also weder ``verdichtungs_aufrufe``
        #: noch die Sekunden. Gemessen an der Decke von 24 verschwanden so
        #: 15 von 24 Werkzeugergebnissen bei null LM-Verdichtungen, und der
        #: Bericht meldete "keine Verdichtung".
        self.gekuerzte_werkzeugausgaben: int = 0
        # summarisation is triggered once the history exceeds 80% of the
        # configured token budget. this keeps the effective context size
        # smaller than the model limit while retaining recent turns.
        self._threshold = int(self.max_tokens * 0.8)

    def close(self) -> None:
        self.memory.close()

    def verdichtungs_zaehler_zuruecksetzen(self) -> None:
        """Die Bilanz des Zusammenfassers auf null setzen.

        Gerufen wird das am ENDE des Turns, von ``turn_usage_snapshot``, das
        die Bilanz verbraucht. Zu Turn-Beginn zurueckzusetzen loeschte die
        Verdichtungen, die beim Anhaengen der Client-Historie entstanden
        waren (routes/copilot.py:357 und :482 haengen an, bevor der
        Orchestrator laeuft): gemessen drei echte Aufrufe, die im Bericht
        fehlten. ``turn_usage_report`` bleibt trotzdem ein Turn-Bericht,
        weil je Turn genau ein Schnappschuss entsteht.
        """
        self.verdichtungs_aufrufe = 0
        self.verdichtungs_sekunden = 0.0
        self.gekuerzte_werkzeugausgaben = 0

    def append(self, message: Dict[str, Any], *, project: "Project" | None = None) -> None:
        """Append a message to the history and summarise if needed.

        If limits are exceeded, :meth:`summarise` is invoked with the provided
        *project* so that summary notes can be persisted.
        """
        self.history.append(message)
        if (
            len(self.history) > self.max_messages
            or self._token_count(self.history) > self._threshold
        ):
            self.summarise(project=project)

    def update_rehydration_state(self, state: Dict[str, Any] | None) -> None:
        self._rehydration_state = self._sanitise_runtime_state(state)

    def clear_rehydration_state(self) -> None:
        self._rehydration_state = {}

    def summarise(
        self,
        project: "Project" | None = None,
        *,
        runtime_state: Dict[str, Any] | None = None,
    ) -> None:
        """Summarise and trim history when limits are exceeded.

        If *project* is provided, newly created summary notes are written to the
        project timeline as JSON records using
        :meth:`candyconc.project.Project.log_op`.
        """
        if runtime_state is not None:
            self.update_rehydration_state(runtime_state)

        while (
            len(self.history) > self.max_messages
            or self._token_count(self.history) > self._threshold
        ) and len(self.history) > 1:
            if self.microcompact(keep_last_messages=max(4, self.max_messages // 3)):
                if (
                    len(self.history) <= self.max_messages
                    and self._token_count(self.history) <= self._threshold
                ):
                    break
            cut = self._normalise_compaction_cut(max(1, len(self.history) // 2))
            if not self._compact_prefix(
                cut,
                project=project,
                runtime_state=self._rehydration_state,
            ):
                break

    def force_compact(
        self,
        *,
        project: "Project" | None = None,
        reason: str = "",
        keep_last_messages: int = 6,
        runtime_state: Dict[str, Any] | None = None,
    ) -> bool:
        """Aggressively compact the oldest part of the history.

        This is used as a recovery path after context-window failures. It keeps
        a small recent tail intact and collapses everything before it into a
        single structured summary note.
        """

        if runtime_state is not None:
            self.update_rehydration_state(runtime_state)

        if len(self.history) <= 1:
            return False

        keep_last_messages = max(1, keep_last_messages)
        changed = False

        if self.microcompact(keep_last_messages=keep_last_messages):
            changed = True
            if (
                len(self.history) <= keep_last_messages
                and self._token_count(self.history) <= self._threshold
            ):
                return True

        while (
            len(self.history) > keep_last_messages
            or self._token_count(self.history) > self._threshold
        ) and len(self.history) > 1:
            target_tail = min(keep_last_messages, max(1, len(self.history) - 1))
            cut = self._normalise_compaction_cut(len(self.history) - target_tail)
            if cut <= 0 or cut >= len(self.history):
                break
            if not self._compact_prefix(
                cut,
                project=project,
                reason=reason,
                runtime_state=self._rehydration_state,
            ):
                break
            changed = True
            if self._token_count(self.history) <= max(self._threshold // 2, 256):
                break

        return changed

    def microcompact(
        self,
        *,
        keep_last_messages: int = 6,
    ) -> bool:
        """Shrink older tool outputs without rewriting turn structure."""

        if len(self.history) <= 1:
            return False

        keep_last_messages = max(1, keep_last_messages)
        cutoff = max(0, len(self.history) - keep_last_messages)
        if cutoff <= 0:
            return False

        changed = False
        for index in range(cutoff):
            message = self.history[index]
            if message.get("role") != "tool":
                continue
            compacted = self._microcompact_tool_message(message)
            if compacted is None:
                continue
            self.history[index] = compacted
            self.gekuerzte_werkzeugausgaben += 1
            changed = True

        return changed

    def get_history(self) -> List[Dict[str, Any]]:
        """Return history including summary and search notes as system messages."""
        notes: List[Dict[str, Any]] = []
        seen: set[str] = set()

        runtime_note = self._render_runtime_state(self._rehydration_state)
        if runtime_note:
            notes.append({"role": "system", "content": runtime_note})

        for note in self._search_results[: self.max_search_messages]:
            cleaned = note.strip()
            rendered = self._render_note(note, "[Relevant prior summary]")
            if rendered is None or cleaned in seen:
                continue
            seen.add(cleaned)
            notes.append({"role": "system", "content": rendered})

        for note in self.summaries[-self.max_summary_messages :]:
            cleaned = note.strip()
            rendered = self._render_note(note, "[Conversation summary]")
            if rendered is None or cleaned in seen:
                continue
            seen.add(cleaned)
            notes.append({"role": "system", "content": rendered})

        return notes + list(self.history)

    def search(self, query: str, k: int = 3) -> List[str]:
        """Search stored summaries for ``query`` and remember the results."""
        results = self.memory.search(query, k)
        self._search_results = results
        return results

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _lm_summary(
        self,
        messages: List[Dict[str, Any]],
        *,
        reason: str = "",
        runtime_state: Dict[str, Any] | None = None,
    ) -> str:
        """Return a summary for ``messages`` via the local language model.

        This method handles both sync and async contexts:
        - From sync context: runs async function with asyncio.run()
        - From async context: uses a thread pool to avoid deadlock
        """
        from . import _lm_chat_async
        import concurrent.futures

        transcript = "\n\n".join(
            self._format_message_for_summary(message) for message in messages
        )
        reason_text = f" Auslöser für diese Komprimierung: {reason}." if reason else ""
        state_payload = self._sanitise_runtime_state(runtime_state or self._rehydration_state)
        prompt = [
            {
                "role": "system",
                "content": (
                    "Du komprimierst den Verlauf eines korpuslinguistischen "
                    "Assistenzsystems. Gib ausschließlich ein JSON-Objekt "
                    "zurück. Nutze genau diese Felder: user_goal, "
                    "active_question, active_filters, active_selection, ui_focus, "
                    "open_clarification, open_approval, current_plan, "
                    "active_analysis_contract, "
                    "grounded_fact_notes, evidence_gaps, blocked_claims, "
                    "last_grounding_verdict, recent_research_findings, background_tasks, "
                    "failed_attempts, recent_recoveries, last_llm_route, "
                    "next_step, reason. "
                    "Listen müssen Arrays aus kurzen Strings sein. "
                    "Nutze nur Fakten aus dem Transcript. Relevante Hinweise aus "
                    "dem Arbeitszustand darfst du nur übernehmen, wenn sie durch "
                    "den Verlauf gestützt werden."
                    f"{reason_text}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Aktueller Arbeitszustand:\n"
                    f"{json.dumps(state_payload, ensure_ascii=False)}\n\n"
                    "Transcript:\n"
                    f"{transcript}"
                ),
            },
        ]

        def run_sync() -> Dict[str, Any]:
            return asyncio.run(_lm_chat_async(prompt, tools=[]))

        # Gebucht wird in ``finally`` und nicht nach dem Erfolg. Ein Aufruf,
        # der in einen Transportfehler laeuft, hat trotzdem Modellzeit
        # gekostet, und das sind die teuersten. CLAUDE.md, Zeitlimits,
        # Regel 3: was entstanden ist, muss erhalten bleiben, einschliesslich
        # der Bilanz des Laufs.
        _verdichtung_start = time.perf_counter()
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                result = run_sync()
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_sync)
                    # The underlying LLM client owns the configured timeout. A
                    # second hardcoded 30-second deadline here turned a merely
                    # busy local model into a failed compaction and discarded
                    # its later valid response.
                    result = future.result()
        finally:
            self.verdichtungs_aufrufe += 1
            self.verdichtungs_sekunden += time.perf_counter() - _verdichtung_start

        raw_summary = self._normalise_summary(result.get("content", ""))
        payload = self._build_structured_summary_payload(
            raw_summary,
            runtime_state=state_payload,
            reason=reason,
        )
        return self._encode_structured_note(payload)

    def _format_message_for_summary(self, message: Dict[str, Any]) -> str:
        role = str(message.get("role", "unknown"))
        parts = [f"role: {role}"]

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            names = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function", {})
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if name:
                    names.append(str(name))
            if names:
                parts.append(f"tool_calls: {', '.join(names)}")

        content = message.get("content", "")
        if role == "tool":
            rendered_content = self._summarise_tool_content(content)
        else:
            rendered_content = self._clip_text(str(content), 900)

        if rendered_content:
            parts.append(f"content: {rendered_content}")

        return "\n".join(parts)

    def _summarise_tool_content(self, content: Any) -> str:
        text = self._clip_text(str(content), 1400)
        try:
            payload = json.loads(text)
        except Exception:
            return text

        if not isinstance(payload, dict):
            return self._clip_text(json.dumps(payload, ensure_ascii=True), 500)

        summary_parts: List[str] = []

        status = payload.get("status")
        if status is not None:
            summary_parts.append(f"status={status}")

        for key in ("message", "error", "summary", "url"):
            value = payload.get(key)
            if value:
                summary_parts.append(f"{key}={self._clip_text(str(value), 180)}")

        for key in ("rows", "offsets", "clusters"):
            value = payload.get(key)
            if isinstance(value, list):
                summary_parts.append(f"{key}={len(value)}")

        tables = payload.get("tables")
        if isinstance(tables, dict):
            summary_parts.append(f"tables={len(tables)}")

        total = payload.get("total")
        if total is not None:
            summary_parts.append(f"total={total}")

        plan = payload.get("plan")
        if isinstance(plan, dict):
            steps = plan.get("steps")
            if isinstance(steps, list):
                summary_parts.append(f"plan_steps={len(steps)}")
            goal = plan.get("goal")
            if goal:
                summary_parts.append(f"plan_goal={self._clip_text(str(goal), 120)}")

        if not summary_parts:
            return self._clip_text(json.dumps(payload, ensure_ascii=True), 500)

        return "; ".join(summary_parts)

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    @staticmethod
    def _normalise_summary(summary: str) -> str:
        lines = [line.rstrip() for line in summary.splitlines()]
        cleaned = "\n".join(line for line in lines if line.strip())
        return cleaned.strip()

    def _render_note(self, note: str, label: str) -> str | None:
        cleaned = note.strip()
        if not cleaned:
            return None
        payload = self._decode_structured_note(cleaned)
        if payload is None:
            return f"{label}\n{cleaned}"
        rendered = self._render_structured_payload(payload)
        if not rendered:
            return None
        return f"{label}\n{rendered}"

    def _compact_prefix(
        self,
        cut: int,
        *,
        project: "Project" | None = None,
        reason: str = "",
        runtime_state: Dict[str, Any] | None = None,
    ) -> bool:
        if cut <= 0:
            return False
        cut = min(cut, len(self.history) - 1)
        to_summarise = self.history[:cut]
        if not to_summarise:
            return False

        summary = self._lm_summary(
            to_summarise,
            reason=reason,
            runtime_state=runtime_state,
        )
        if summary:
            self.summaries.append(summary)
            self.memory.add(summary)
            if project:
                project.log_op(json.dumps({"summary": summary}))

        self.history = self.history[cut:]
        return True

    def _microcompact_tool_message(
        self,
        message: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        content = str(message.get("content", ""))
        if not content:
            return None

        try:
            payload = json.loads(content)
        except Exception:
            payload = None

        if isinstance(payload, dict) and payload.get("status") == self._MICROCOMPACT_STATUS:
            return None

        summary = self._summarise_tool_content(content)
        if not summary:
            return None

        compacted_content = json.dumps(
            {
                "status": self._MICROCOMPACT_STATUS,
                "summary": self._clip_text(summary, 220),
            },
            ensure_ascii=False,
        )
        if len(compacted_content) >= len(content):
            return None

        updated = dict(message)
        updated["content"] = compacted_content
        return updated

    def _normalise_compaction_cut(self, cut: int) -> int:
        """Avoid splitting assistant tool calls from their tool results."""

        if len(self.history) <= 1:
            return 0

        cut = max(1, min(cut, len(self.history) - 1))

        while cut < len(self.history) and self.history[cut].get("role") == "tool":
            cut += 1

        if cut >= len(self.history):
            # Move the cut before the assistant call so its tool results keep
            # their matching call. Zero means nothing can be compacted.
            cut = len(self.history) - 1
            while cut > 0 and self.history[cut].get("role") == "tool":
                cut -= 1
            return cut

        previous = self.history[cut - 1]
        if previous.get("role") == "assistant" and previous.get("tool_calls"):
            while cut < len(self.history) and self.history[cut].get("role") == "tool":
                cut += 1

        return max(1, min(cut, len(self.history) - 1))

    def _build_structured_summary_payload(
        self,
        raw_summary: str,
        *,
        runtime_state: Dict[str, Any] | None,
        reason: str,
    ) -> Dict[str, Any]:
        payload = self._sanitise_runtime_state(runtime_state)
        parsed = self._extract_json_object(raw_summary)
        if isinstance(parsed, dict):
            for field in self._SUMMARY_FIELDS:
                if field not in parsed:
                    continue
                value = parsed.get(field)
                if field in {
                    "grounded_fact_notes",
                    "evidence_gaps",
                    "blocked_claims",
                    "failed_attempts",
                    "recent_recoveries",
                    "recent_research_findings",
                    "background_tasks",
                }:
                    items = self._normalise_list(value, max_items=5, item_limit=220)
                    if items:
                        payload[field] = items
                    continue
                rendered = self._serialise_value(value, limit=280)
                if rendered:
                    payload[field] = rendered

        # Was das Modell unter dem Beleg-Namen geschickt hat, ist
        # Modellprosa wie jede andere. Es geht nicht verloren, es bekommt
        # nur das Etikett, das es verdient.
        if isinstance(parsed, dict):
            _modelleigen = self._normalise_list(
                parsed.get("last_valid_tool_results"), max_items=5, item_limit=220)
            if _modelleigen:
                payload.setdefault("modell_zusammenfassung", []).extend(_modelleigen)

        # Nur wenn das Modell das Format GANZ verfehlt hat. War die Antwort
        # lesbares JSON, ist der Rohtext bereits in Feldern aufgegangen,
        # und ihn zusaetzlich als Prosa anzuhaengen erzeugt eine
        # Ueberschrift ohne Inhalt.
        if raw_summary and not isinstance(parsed, dict):
            # NICHT unter "last_valid_tool_results". Liefert das Modell auf
            # die Zusammenfassungsbitte Prosa statt JSON, so ist diese Prosa
            # eine unbelegte Modellaussage. Sie landete hier im selben Fach
            # wie die echten Werkzeugergebnisse aus
            # ``orchestrator._recent_tool_results`` (nur solche mit ok=True)
            # und wurde dem naechsten Turn unter der Ueberschrift "Letzte
            # belastbare Tool-Ergebnisse" vorgelegt. Damit trug erfundener
            # Text ein Beleg-Etikett, und zwar genau an der Stelle, an der
            # der naechste Turn nach Belegen sucht.
            #
            # Der Text bleibt erhalten, denn er ist der einzige Rest der
            # gekappten Historie. Er bekommt nur ein Etikett, das sagt, was
            # er ist.
            payload["modell_zusammenfassung"] = [self._clip_text(raw_summary, 220)]

        if reason:
            payload["reason"] = self._clip_text(reason, 160)

        if not payload.get("next_step"):
            if payload.get("open_clarification"):
                payload["next_step"] = "Erst die offene Rueckfrage auflösen, dann fortsetzen."
            elif payload.get("open_approval"):
                payload["next_step"] = "Auf Freigabe warten oder eine reversible Alternative wählen."
            else:
                payload["next_step"] = "Mit dem letzten belastbaren Zustand weiterarbeiten."

        return payload

    def _render_runtime_state(self, state: Dict[str, Any]) -> str | None:
        payload = self._sanitise_runtime_state(state)
        if not payload:
            return None
        rendered = self._render_structured_payload(payload)
        if not rendered:
            return None
        return f"[Aktueller Arbeitszustand]\n{rendered}"

    def _render_structured_payload(self, payload: Dict[str, Any]) -> str:
        lines: List[str] = []
        if payload.get("user_goal"):
            lines.append(f"Nutzerziel: {payload['user_goal']}")
        if payload.get("active_question"):
            lines.append(f"Aktive Frage: {payload['active_question']}")
        if payload.get("active_filters"):
            lines.append(f"Aktive Filter: {payload['active_filters']}")
        if payload.get("active_selection"):
            lines.append(f"Aktive Auswahl: {payload['active_selection']}")
        if payload.get("ui_focus"):
            lines.append(f"UI-Fokus: {payload['ui_focus']}")
        if payload.get("open_clarification"):
            lines.append(f"Offene Rueckfrage: {payload['open_clarification']}")
        if payload.get("open_approval"):
            lines.append(f"Offene Freigabe: {payload['open_approval']}")
        if payload.get("current_plan"):
            lines.append(f"Aktueller Plan: {payload['current_plan']}")
        if payload.get("active_analysis_contract"):
            lines.append(f"Aktiver Analysevertrag: {payload['active_analysis_contract']}")
        research_contexts = payload.get("research_contexts")
        has_research_contexts = isinstance(research_contexts, list) and bool(research_contexts)
        if has_research_contexts:
            lines.append("Research-Kontexte:")
            for item in research_contexts[:4]:
                if not isinstance(item, dict):
                    continue
                lines.extend(self._render_research_context(item))
        for label, key in (
            ("Letzte belastbare Tool-Ergebnisse", "last_valid_tool_results"),
            ("Modell-Zusammenfassung (unbelegte Prosa, kein Werkzeugergebnis)",
             "modell_zusammenfassung"),
            ("Grounded Facts", "grounded_fact_notes"),
            ("Evidenzluecken", "evidence_gaps"),
            ("Blockierte Claims", "blocked_claims"),
            ("Research-Befunde", "recent_research_findings"),
            ("Hintergrund-Tasks", "background_tasks"),
            ("Nicht stumpf wiederholen", "failed_attempts"),
            ("Juengste Recoveries", "recent_recoveries"),
        ):
            if has_research_contexts and key in {"recent_research_findings", "background_tasks"}:
                continue
            items = payload.get(key)
            if not isinstance(items, list) or not items:
                continue
            lines.append(f"{label}:")
            for item in items[:5]:
                lines.append(f"- {self._clip_text(str(item), 220)}")
        if payload.get("last_grounding_verdict"):
            lines.append(f"Letztes Grounding-Urteil: {payload['last_grounding_verdict']}")
        if payload.get("last_llm_route"):
            lines.append(f"Letzter LLM-Pfad: {payload['last_llm_route']}")
        if payload.get("next_step"):
            lines.append(f"Nächster sinnvoller Schritt: {payload['next_step']}")
        if payload.get("reason"):
            lines.append(f"Kompaktierungsgrund: {payload['reason']}")
        return "\n".join(lines).strip()

    def _sanitise_runtime_state(self, state: Dict[str, Any] | None) -> Dict[str, Any]:
        if not isinstance(state, dict):
            return {}

        payload: Dict[str, Any] = {}
        for field in (
            "user_goal",
            "active_question",
            "ui_focus",
            "open_clarification",
            "open_approval",
            "current_plan",
            "active_analysis_contract",
            "last_grounding_verdict",
            "last_llm_route",
            "next_step",
            "reason",
        ):
            value = self._serialise_value(state.get(field), limit=220)
            if value:
                payload[field] = value

        for field in ("active_filters", "active_selection"):
            value = self._serialise_value(state.get(field), limit=280)
            if value:
                payload[field] = value

        for field in (
            "last_valid_tool_results",
            "modell_zusammenfassung",
            "grounded_fact_notes",
            "evidence_gaps",
            "blocked_claims",
            "failed_attempts",
            "recent_recoveries",
            "recent_research_findings",
            "background_tasks",
        ):
            items = self._normalise_list(state.get(field), max_items=5, item_limit=220)
            if items:
                payload[field] = items
        research_contexts = self._normalise_research_contexts(state.get("research_contexts"), max_items=4)
        if research_contexts:
            payload["research_contexts"] = research_contexts

        return payload

    def _encode_structured_note(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self._STRUCTURED_NOTE_PREFIX}"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )

    def _decode_structured_note(self, note: str) -> Dict[str, Any] | None:
        if not note.startswith(self._STRUCTURED_NOTE_PREFIX):
            return None
        raw = note[len(self._STRUCTURED_NOTE_PREFIX) :].strip()
        try:
            decoded = json.loads(raw)
        except Exception:
            return None
        if not isinstance(decoded, dict):
            return None
        return self._sanitise_runtime_state(decoded)

    def _normalise_list(
        self,
        value: Any,
        *,
        max_items: int,
        item_limit: int,
    ) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        result: List[str] = []
        seen: set[str] = set()
        for item in value:
            rendered = self._serialise_value(item, limit=item_limit)
            if not rendered or rendered in seen:
                continue
            seen.add(rendered)
            result.append(rendered)
            if len(result) >= max_items:
                break
        return result

    def _normalise_research_contexts(
        self,
        value: Any,
        *,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: List[Dict[str, Any]] = []
        for item in value:
            normalised = self._normalise_research_context(item)
            if not normalised:
                continue
            result.append(normalised)
            if len(result) >= max_items:
                break
        return result

    def _normalise_research_context(self, item: Any) -> Dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        payload: Dict[str, Any] = {}
        for field, limit in (("task", 24), ("status", 32), ("question", 180)):
            value = self._serialise_value(item.get(field), limit=limit)
            if value:
                payload[field] = value
        scope = item.get("scope", {})
        if isinstance(scope, dict):
            normalised_scope: Dict[str, Any] = {}
            for field in (
                "corpus",
                "tab",
                "mode",
                "view",
                "view_fingerprint",
                "query_context",
                "query_context_fingerprint",
                "filters",
                "selection",
                "results",
                "visible_rows",
            ):
                value = self._serialise_value(scope.get(field), limit=140)
                if value:
                    normalised_scope[field] = value
            if normalised_scope:
                payload["scope"] = normalised_scope
        findings = self._normalise_list(item.get("findings"), max_items=3, item_limit=180)
        if findings:
            payload["findings"] = findings
        tools = self._normalise_list(item.get("tools"), max_items=3, item_limit=80)
        if tools:
            payload["tools"] = tools
        dependencies = self._normalise_list(item.get("dependencies"), max_items=5, item_limit=32)
        if dependencies:
            payload["dependencies"] = dependencies
        analysis_family = self._serialise_value(item.get("analysis_family"), limit=40)
        if analysis_family:
            payload["analysis_family"] = analysis_family
        grounding_verdict = self._serialise_value(item.get("grounding_verdict"), limit=80)
        if grounding_verdict:
            payload["grounding_verdict"] = grounding_verdict
        observed_fact_ids = self._normalise_list(item.get("observed_fact_ids"), max_items=6, item_limit=40)
        if observed_fact_ids:
            payload["observed_fact_ids"] = observed_fact_ids
        evidence_manifest = self._normalise_list(item.get("evidence_manifest"), max_items=6, item_limit=180)
        if evidence_manifest:
            payload["evidence_manifest"] = evidence_manifest
        return payload or None

    def _render_research_context(self, item: Dict[str, Any]) -> List[str]:
        head_parts: List[str] = []
        for field in ("task", "status"):
            value = str(item.get(field, "") or "").strip()
            if value:
                head_parts.append(value)
        scope = item.get("scope", {})
        if isinstance(scope, dict):
            for field in ("corpus", "tab", "mode", "filters", "selection", "results"):
                value = str(scope.get(field, "") or "").strip()
                if value:
                    head_parts.append(value)
        lines = [f"- {self._clip_text(' | '.join(head_parts), 220)}"] if head_parts else []
        if isinstance(scope, dict):
            detail_parts: List[str] = []
            for field, label in (
                ("view", "Ansicht"),
                ("view_fingerprint", "V-Fingerprint"),
                ("query_context", "Query-Kontext"),
                ("query_context_fingerprint", "Q-Fingerprint"),
                ("visible_rows", "Vorschau"),
            ):
                value = str(scope.get(field, "") or "").strip()
                if value:
                    detail_parts.append(f"{label}: {value}")
            if detail_parts:
                lines.append(f"  Scope: {' | '.join(detail_parts)}")
        question = str(item.get("question", "") or "").strip()
        if question:
            lines.append(f"  Frage: {self._clip_text(question, 220)}")
        analysis_family = str(item.get("analysis_family", "") or "").strip()
        if analysis_family:
            lines.append(f"  Analysefamilie: {self._clip_text(analysis_family, 80)}")
        grounding_verdict = str(item.get("grounding_verdict", "") or "").strip()
        if grounding_verdict:
            lines.append(f"  Grounding: {self._clip_text(grounding_verdict, 80)}")
        dependencies = item.get("dependencies", [])
        if isinstance(dependencies, list) and dependencies:
            lines.append(f"  Baut auf: {', '.join(self._clip_text(str(entry), 24) for entry in dependencies[:5])}")
        observed_fact_ids = item.get("observed_fact_ids", [])
        if isinstance(observed_fact_ids, list) and observed_fact_ids:
            lines.append(f"  Facts: {', '.join(self._clip_text(str(entry), 24) for entry in observed_fact_ids[:6])}")
        evidence_manifest = item.get("evidence_manifest", [])
        if isinstance(evidence_manifest, list) and evidence_manifest:
            lines.append("  Evidenz:")
            for entry in evidence_manifest[:4]:
                lines.append(f"  - {self._clip_text(str(entry), 180)}")
        findings = item.get("findings", [])
        if isinstance(findings, list) and findings:
            lines.append(f"  Befunde: {' || '.join(self._clip_text(str(entry), 160) for entry in findings[:3])}")
        tools = item.get("tools", [])
        if isinstance(tools, list) and tools:
            lines.append(f"  Tools: {', '.join(self._clip_text(str(entry), 40) for entry in tools[:3])}")
        return lines

    def _serialise_value(self, value: Any, *, limit: int) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return self._clip_text(value, limit)
        try:
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            rendered = str(value)
        return self._clip_text(rendered, limit)

    @staticmethod
    def _extract_json_object(text: str) -> Dict[str, Any] | None:
        stripped = text.strip()
        if not stripped:
            return None
        candidates = [stripped]
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            candidates.append(stripped[start : end + 1])
        for candidate in candidates:
            try:
                decoded = json.loads(candidate)
            except Exception:
                continue
            if isinstance(decoded, dict):
                return decoded
        return None

    @staticmethod
    def _token_count(messages: List[Dict[str, Any]]) -> int:
        """Woerter der Historie. Das ist die Einheit der Verdichtungsschwelle.

        Hier stand eine Verzweigung ueber ``tiktoken``: war das Paket
        importierbar UND kannte ``encoding_for_model`` den Modellnamen,
        zaehlte diese Funktion Tokens, sonst ``split``-Woerter. Die Einheit
        des Budgets hing damit am venv, ohne dass irgendwo etwas rot wurde.

        Die Schwelle in ``sitzungsverdichtung`` ist eine WORTMESSUNG: die
        groesste gemessene Modellsicht eines Werkzeugergebnisses sind 652
        Woerter (KWIC mit 50 Zeilen). In Tokens gerechnet traegt dieselbe
        Zahl deutlich weniger Werkzeugergebnisse, und die zugesicherte
        Rohheit der Evidenz fiele still weg. ``tiktoken`` steht in
        requirements.txt:17, fehlt in diesem venv aber, die Verzweigung war
        also nie am Werk: ihr Wegfall aendert am gemessenen Verhalten
        nichts, er legt nur die Einheit fest.

        Diese Funktion ist der EINZIGE Zaehler dieser Schwelle
        (session_manager.py:141, 168, 173, 211, 217, 231).
        """
        return sum(
            len(str(message.get("content", "")).split()) for message in messages
        )
