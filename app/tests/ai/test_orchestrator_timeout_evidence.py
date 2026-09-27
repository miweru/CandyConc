"""Regression test: a run that hits its time budget must not throw away the
tool evidence it already gathered.

Before the fix, the timeout branch in ``run_async`` appended an empty assistant
message and returned ``""`` -- handing the user a blank answer even though tool
results were already in hand. The fix mirrors the ``max_steps`` exhaustion path
and finalizes the best grounded/partial answer from the collected evidence.

The bootstrap mirrors ``test_orchestrator_grounding_runtime`` so the real
orchestrator module is exercised with injected fakes (no live LLM).
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
backend_mod.copilot_event_bus = types.SimpleNamespace(
    publish=lambda event, session_id=None: _events.append(event)
)
services_pkg.backend = backend_mod

orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
spec = importlib.util.spec_from_file_location("candyconc_copilot.orchestrator", orch_path)
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
    "candyconc_copilot.policy_engine",
    PolicyEngine=_PolicyEngine,
)
sys.modules["candyconc_copilot.observability"] = _module(
    "candyconc_copilot.observability",
    Observability=_Observability,
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
    # R2 KV-split + Waechter-Rollen-Aenderung (a038abb3e1): der Runtime-
    # Guard reist als USER-Nachricht mit [System note:]-Wrapper ans Ende;
    # das JSON-Payload ist die letzte User-Nachricht, deren Inhalt
    # tatsaechlich JSON ist (mit '{' beginnt).
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if content.lstrip().startswith("{"):
            return json.loads(content)
    raise AssertionError("kein JSON-Payload in den Struktur-Nachrichten")


def _accept_contract_review(payload: dict, *, analysis_family: str, required_evidence: list[str]) -> dict:
    proposed = dict(payload.get("proposed_contract", {}) or {})
    return _response(
        {
            "verdict": "accept",
            "analysis_family": analysis_family or proposed.get("analysis_family", "open_research"),
            "required_evidence": list(required_evidence),
            "response_shape": proposed.get("response_shape", ""),
            "clarification_question": "",
            "reason": "Vertrag ist hinreichend eng und evidenzgebunden.",
        }
    )


class TestOrchestratorTimeoutEvidence(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _events.clear()

    async def test_timeout_returns_grounded_answer_from_collected_evidence(self):
        tools = [
            {"type": "function", "function": {"name": "frequency_list", "parameters": {"type": "object"}}},
        ]
        dispatched: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                schema_name = json_schema.get("name", "")
                if schema_name == "analysis_contract":
                    return _response(
                        {
                            "mode": "tool_analysis",
                            "analysis_family": "term_frequency",
                            "question_scope": "Frequenz von Zeit",
                            "allowed_tools": [],
                            "required_evidence": ["frequency_rows"],
                            "forbidden_claims": ["unsupported counts"],
                            "response_shape": "kurz",
                            "needs_clarification": False,
                            "clarification_question": "",
                        }
                    )
                if schema_name == "contract_review":
                    return _accept_contract_review(
                        _structured_payload(messages),
                        analysis_family="term_frequency",
                        required_evidence=["frequency_rows"],
                    )
                if schema_name == "answer_envelope":
                    payload = _structured_payload(messages)
                    facts = payload.get("observed_facts", [])
                    return _response(
                        {
                            "claims": [
                                {
                                    "id": "claim_good",
                                    "claim_kind": "observation",
                                    "text": "'Zeit' kommt 12-mal vor.",
                                    "fact_ids": [facts[0]["id"]] if facts else [],
                                    "assertion_level": "exact",
                                }
                            ],
                            "answer_markdown": "Belegte Antwort",
                            "evidence_gaps": [],
                            "blocked_claims": [],
                        }
                    )
                if schema_name == "grounding_verdict":
                    payload = _structured_payload(messages)
                    claim_ids = [
                        claim["id"]
                        for claim in payload.get("answer_envelope", {}).get(
                            "claims", []
                        )
                    ]
                    return _response(
                        {
                            "verdict": "pass",
                            "accepted_claim_ids": claim_ids,
                            "rejected_claim_ids": [],
                            "reasons": [],
                            "needs_retry": False,
                        }
                    )
                raise AssertionError(f"unexpected schema {schema_name}")

            # Non-structured turn: always request another tool call so the loop
            # never finalizes on its own and the time budget is what stops it.
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": f"call_{len(dispatched)}",
                                    "type": "function",
                                    "function": {
                                        "name": "frequency_list",
                                        "arguments": json.dumps({"stopwords": []}, ensure_ascii=False),
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

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return {
                "status": "success",
                "rows": [{"word": "Zeit", "f": 12}],
                "total": 1,
            }

        orch = ReActOrchestrator(tools, _call_llm, _dispatch)
        # max_time=0 forces the timeout branch on the first time-budget check,
        # after at least one tool batch has produced evidence.
        result = await orch.run_async("Wie oft kommt Zeit vor?", max_time=0.0)

        self.assertTrue(dispatched, "at least one tool should have run before timeout")
        self.assertTrue(
            result,
            "timeout must not return an empty answer when evidence was collected",
        )
        self.assertNotEqual(result, "")
        # The answer is derived from the collected evidence (grounded path),
        # not a blank string. Assistant content persisted to the session must
        # also be non-empty.
        last_assistant = [
            m for m in orch.session.history if m.get("role") == "assistant"
        ][-1]
        self.assertTrue(last_assistant.get("content"))


if __name__ == "__main__":
    unittest.main()
