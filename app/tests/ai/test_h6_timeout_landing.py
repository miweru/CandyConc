"""H6 (B1): Kooperative Timeout-Landung ist eine Antwort, keine Kapitulation.

Vorher ersetzte die Timeout-Landung ein ``None`` der deterministischen
Finalisierung direkt durch das fail-closed-Markdown ("Ich kann diese
Analyse gerade nicht sicher tool-gestützt beantworten."), obwohl der
callfreie Salvage-Evidenzbericht (``build_salvage_markdown``) im selben
Codebestand existiert. Jetzt landet der Timeout ueber
``_finalize_grounded_answer(deterministic_only=True)``: erst Salvage aus
der Turn-Evidenz, fail-closed nur bei wirklich leerer Evidenz.

K1-Invariante: nach dem Timeout-Schalter laufen KEINE weiteren LLM-Calls
(``deterministic_only=True`` schneidet die LLM-Zweige ab, Salvage und
fail-closed sind callfrei). Der Fake-LLM-Callzaehler beweist das.

Bootstrap gespiegelt aus ``test_orchestrator_timeout_evidence.py``
(reales Orchestrator-Modul mit injizierten Fakes, kein Live-LLM).
"""

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


root = Path(__file__).resolve().parents[2]
package_root = root / "src" / "candyconc" / "candyconc_copilot"


def _module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


pkg = sys.modules.setdefault("candyconc_copilot", types.ModuleType("candyconc_copilot"))
pkg.__path__ = [str(package_root)]  # type: ignore[attr-defined]

try:
    import fastapi as _fastapi  # noqa: F401
except Exception:
    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = _module("fastapi", HTTPException=_HTTPException)

candyconc_pkg = sys.modules.setdefault("candyconc", types.ModuleType("candyconc"))
candyconc_pkg.__path__ = [str(root / "src" / "candyconc")]  # type: ignore[attr-defined]
core_pkg = sys.modules.setdefault("candyconc.core", types.ModuleType("candyconc.core"))
lineage_mod = sys.modules.setdefault(
    "candyconc.core.lineage",
    _module("candyconc.core.lineage", log_tool=lambda *args, **kwargs: None),
)
core_pkg.lineage = lineage_mod
tooling_pkg = sys.modules.setdefault("candyconc.tooling", types.ModuleType("candyconc.tooling"))
tooling_pkg.__path__ = [str(root / "src" / "candyconc" / "tooling")]  # type: ignore[attr-defined]
sys.modules.setdefault(
    "candyconc.tooling.registry",
    _module(
        "candyconc.tooling.registry",
        get_tool_runtime_info=lambda *args, **kwargs: {
            "frequency_list": {"read_only": True},
        },
    ),
)
services_pkg = sys.modules.setdefault("candyconc.services", types.ModuleType("candyconc.services"))
services_pkg.__path__ = [str(root / "src" / "candyconc" / "services")]  # type: ignore[attr-defined]

try:
    import candyconc.services.llm_client as _real_llm_client  # noqa: F401
except Exception:
    class _LLMRequestError(Exception):
        def __init__(self, message="", *, kind="transient", detail=None, retryable=False, route=None, model=None):
            super().__init__(message)
            self.message = message
            self.detail = detail or message
            self.kind = kind
            self.retryable = retryable
            self.route = route
            self.model = model
            self.retry_after = None

    sys.modules.setdefault(
        "candyconc.services.llm_client",
        _module(
            "candyconc.services.llm_client",
            LLMErrorKind=types.SimpleNamespace(
                CONTEXT_WINDOW_EXCEEDED="context_window_exceeded",
                MAX_OUTPUT_TOKENS="max_output_tokens",
                TRANSIENT="transient",
            ),
            LLMRequestError=_LLMRequestError,
        ),
    )

_events: list[dict] = []
backend_mod = sys.modules.setdefault(
    "candyconc.services.backend",
    types.ModuleType("candyconc.services.backend"),
)
backend_mod.__path__ = [str(root / "src" / "candyconc" / "services" / "backend")]  # type: ignore[attr-defined]
if not hasattr(backend_mod, "copilot_event_bus"):
    backend_mod.copilot_event_bus = types.SimpleNamespace(
        publish=lambda event, session_id=None: _events.append(event)
    )
services_pkg.backend = backend_mod

orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
spec = importlib.util.spec_from_file_location(
    "candyconc_copilot.orchestrator_h6_timeout", orch_path
)
orch_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader


class _PolicyEngine:
    def __init__(self, *args, **kwargs):
        self.project = kwargs.get("project")

    def get(self, _user, _key, default=None):
        return default

    def check(self, _role, _tool, _tokens):
        return {"status": "ok"}


class _Observability:
    def record(self, *args, **kwargs):
        return None

    def span(self, *args, **kwargs):
        class _Dummy:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def set_attribute(self, *a, **k):
                return None

        return _Dummy()


sys.modules["candyconc_copilot.policy_engine"] = _module(
    "candyconc_copilot.policy_engine", PolicyEngine=_PolicyEngine
)
sys.modules["candyconc_copilot.observability"] = _module(
    "candyconc_copilot.observability", Observability=_Observability
)
for mod_name in [
    "candyconc_copilot.memory_store",
    "candyconc_copilot.session_manager",
    "candyconc_copilot.prompts",
]:
    path = root / "src" / "candyconc" / "candyconc_copilot" / f"{mod_name.split('.')[-1]}.py"
    m_spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(m_spec)
    assert m_spec and m_spec.loader
    m_spec.loader.exec_module(module)  # type: ignore[arg-type]
    sys.modules[mod_name] = module
spec.loader.exec_module(orch_module)  # type: ignore[arg-type]
ReActOrchestrator = orch_module.ReActOrchestrator

CAPITULATION_LINE = (
    "Ich kann diese Analyse gerade nicht sicher tool-gestützt beantworten."
)
SALVAGE_NOTE = "Der Turn wurde vor der vollstaendigen Verifikation beendet"


def _response(payload: object, *, route: str = "chat:test", model: str = "ground-model") -> dict:
    if isinstance(payload, (dict, list)):
        content = json.dumps(payload, ensure_ascii=False)
    else:
        content = str(payload)
    return {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "_cc_route": route,
        "_cc_model": model,
    }


def _structured_payload(messages) -> dict:
    # Waechter-Rollen-Aenderung (a038abb3e1): der Runtime-Guard reist als
    # USER-Nachricht mit [System note:]-Wrapper ans Ende; das JSON-Payload
    # ist die letzte User-Nachricht, deren Inhalt wirklich JSON ist.
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if content.lstrip().startswith("{"):
            return json.loads(content)
    raise AssertionError("kein User-Payload in den Struktur-Nachrichten")


def _make_call_llm(call_log: list):
    """Fake-LLM: Kontrakt-Preflight + endlose Tool-Runden (nie finalisieren).

    Ein nicht-faktischer Kontrakt (open_research/overview), damit die
    deterministische Faktantwort NICHT greift und die Timeout-Landung
    selbst entscheiden muss (Salvage vs. Kapitulation).
    """

    async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
        _ = exposed_tools, stream, kwargs
        if json_schema is not None:
            schema_name = json_schema.get("name", "")
            call_log.append(f"schema:{schema_name}")
            if schema_name == "analysis_contract":
                return _response(
                    {
                        "mode": "tool_analysis",
                        "analysis_family": "open_research",
                        "question_scope": "Freie Korpus-Exploration",
                        "allowed_tools": [],
                        "required_evidence": [],
                        "forbidden_claims": ["unsupported counts"],
                        "response_shape": "kompakt",
                        "deliverable_kind": "overview",
                        "needs_clarification": False,
                        "clarification_question": "",
                    }
                )
            if schema_name == "contract_review":
                proposed = dict(
                    _structured_payload(messages).get("proposed_contract", {})
                    or {}
                )
                return _response(
                    {
                        "verdict": "accept",
                        "analysis_family": proposed.get(
                            "analysis_family", "open_research"
                        ),
                        "required_evidence": [],
                        "response_shape": proposed.get("response_shape", ""),
                        "clarification_question": "",
                        "reason": "Vertrag ist hinreichend eng.",
                    }
                )
            raise AssertionError(
                "K1 verletzt: unerwarteter Struktur-Call nach dem "
                f"Timeout-Schalter ({schema_name})"
            )
        call_log.append("loop")
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": f"call_{len(call_log)}",
                                "type": "function",
                                "function": {
                                    "name": "frequency_list",
                                    "arguments": json.dumps(
                                        {"stopwords": []}, ensure_ascii=False
                                    ),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "_cc_route": "chat:freq",
            "_cc_model": "ground-model",
        }

    return _call_llm


_TOOLS = [
    {"type": "function", "function": {"name": "frequency_list", "parameters": {"type": "object"}}},
]


class TestTimeoutLandingH6(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _events.clear()

    async def test_timeout_with_evidence_lands_salvage_not_capitulation(self):
        call_log: list = []

        async def _dispatch(tool_call, _token=None):
            return {
                "status": "success",
                "rows": [
                    {"word": "Zeit", "f": 12},
                    {"word": "Arbeit", "f": 5},
                ],
                "total": 2,
            }

        orch = ReActOrchestrator(_TOOLS, _make_call_llm(call_log), _dispatch)
        result = await orch.run_async(
            "Erkunde das Korpus frei: Welche drei Beobachtungen sind am "
            "interessantesten?",
            max_time=0.0,
        )

        self.assertTrue(result)
        # B1: Salvage-Evidenzbericht statt Kapitulation.
        self.assertNotIn(CAPITULATION_LINE, result)
        self.assertIn(SALVAGE_NOTE, result)
        # K1: exakt 2 Struktur-Calls (Preflight) + 1 Loop-Call, danach
        # NICHTS mehr — der Timeout finalisiert callfrei.
        self.assertEqual(
            call_log,
            ["schema:analysis_contract", "schema:contract_review", "loop"],
        )

    async def test_timeout_with_error_evidence_stays_honest_salvage(self):
        # Nur Fehler-Evidenz: der Salvage-Bericht bleibt ehrlich leer
        # ("keine hinreichend belegten Beobachtungen"), erfindet nichts und
        # traegt die Salvage-Annotation.
        call_log: list = []

        async def _dispatch(tool_call, _token=None):
            return {"status": "error", "message": "Index nicht erreichbar"}

        orch = ReActOrchestrator(_TOOLS, _make_call_llm(call_log), _dispatch)
        result = await orch.run_async(
            "Erkunde das Korpus frei: Welche drei Beobachtungen sind am "
            "interessantesten?",
            max_time=0.0,
        )

        self.assertTrue(result)
        self.assertNotIn(CAPITULATION_LINE, result)
        self.assertNotIn("AnalysisContract", result)
        self.assertIn(SALVAGE_NOTE, result)
        self.assertEqual(
            call_log,
            ["schema:analysis_contract", "schema:contract_review", "loop"],
        )

    async def test_timeout_with_empty_evidence_lands_fail_closed_new_text(self):
        # Wirklich leere Evidenz (der einzige Tool-Call wird geblockt, kein
        # Evidenz-Item entsteht): weiterhin ehrlicher fail-closed-Text mit
        # byte-identischer Zeile 1 und der NEUEN Limitationszeile — die
        # alte AnalysisContract-Floskel ist ersetzt. Seit H11/B1 traegt die
        # Exploration eine termlose Schritt-1-Vorplanung; sie wird hier
        # neutralisiert, damit das Szenario "leere Evidenz" bestehen bleibt
        # (die Vorplanung selbst pinnt test_h11_b1_b2_generic_mechanics).
        call_log: list = []
        base = _make_call_llm(call_log)

        async def _call_llm(messages, tools, json_schema=None, stream=False, **kw):
            resp = await base(
                messages, tools, json_schema=json_schema, stream=stream, **kw
            )
            if json_schema is None:
                resp["choices"][0]["message"]["tool_calls"][0]["function"][
                    "name"
                ] = "does_not_exist"
            return resp

        async def _dispatch(tool_call, _token=None):
            raise AssertionError("geblockter Tool-Call darf nie dispatchen")

        orch = ReActOrchestrator(_TOOLS, _call_llm, _dispatch)
        original_preplan = orch_module.preplan_with_contract
        # H11.4: Naht heisst jetzt preplan_with_contract und liefert
        # (calls, erweiterte_kontrakt_tools).
        orch_module.preplan_with_contract = lambda *a, **k: ([], [])
        try:
            result = await orch.run_async(
                "Erkunde das Korpus frei: Welche drei Beobachtungen sind am "
                "interessantesten?",
                max_time=0.0,
            )
        finally:
            orch_module.preplan_with_contract = original_preplan

        self.assertTrue(result)
        self.assertEqual(result.split("\n")[0], CAPITULATION_LINE)
        self.assertIn(
            "- Es liegt keine belegbare Tool-Evidenz für eine Analyse vor.",
            result,
        )
        self.assertNotIn("AnalysisContract", result)
        self.assertEqual(len(orch._turn_evidence_items), 0)


if __name__ == "__main__":
    unittest.main()
