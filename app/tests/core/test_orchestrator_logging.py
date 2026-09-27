"""Project-timeline logging contract of the ReAct orchestrator.

Contract under test (orchestrator.py / core/lineage.py / session_manager.py):
  - every executed tool call is recorded in the project timeline as a JSON
    record with a "tool" key (orchestrator run loop -> lineage.log_tool ->
    Project.log_op),
  - history compaction writes {"summary": ...} records
    (SessionManager._compact_prefix -> Project.log_op).

Test-environment adaptations vs. the original SQLite-era test:
  - tests/conftest.py installs a STUB copilot package in sys.modules whose
    SessionManager has no ``_lm_summary`` and whose orchestrator does not log
    to the project timeline.  The REAL modules are loaded via the established
    loader ``tests/ai/_real_copilot.py`` (spec_from_file_location with
    sys.modules save/restore), exactly like the tests/ai suite does.
  - Project rejects a pre-existing empty file ("Projektdatei unlesbar",
    project.py:_load), so the project path must not exist yet.
  - call_llm is invoked as call_llm(messages, tools, user=..., policy=...,
    [stream=...]) (orchestrator.py:_ra_invoke_llm), and messages always start
    with a system prompt — the dummy switches on "has a tool result arrived
    yet", not on message count, and must accept **kwargs.
  - Tool-backed analysis is fail-closed behind an AnalysisContract. A dummy
    LLM without json_schema support only gets one via the heuristic KWIC
    contract (analysis_grounding.py:heuristic_analysis_contract), so the
    question must be KWIC-shaped.
  - SessionManager._lm_summary calls the real local LLM endpoint; it is
    patched to a canned note so the summary-logging path runs offline and
    deterministically.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from candyconc.project import Project

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import SessionManager, make_orchestrator

RUN_CQLF_TOOL = {
    "type": "function",
    "function": {
        "name": "run_cqlf_query",
        "description": "Run a CQLF/KWIC query against the corpus.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


def dummy_call(messages, tools, **kwargs):
    has_tool_result = any(m.get("role") == "tool" for m in messages)
    if not has_tool_result:
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "1",
                                "type": "function",
                                "function": {
                                    "name": "run_cqlf_query",
                                    "arguments": json.dumps({"query": "fox"}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    return {"choices": [{"message": {"content": "done"}}]}


def dummy_dispatch(call, token=None):
    return {
        "status": "success",
        "rows": [{"left": "the quick brown", "match": "fox", "right": "jumps over"}],
    }


class TestOrchestratorLogging(unittest.TestCase):
    def test_project_timeline_records_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "proj.ccproj"
            project = Project(path)
            session = SessionManager(max_messages=2)
            orch = make_orchestrator(
                [RUN_CQLF_TOOL],
                dummy_call,
                dummy_dispatch,
                session=session,
                project=project,
            )
            orch._tool_runtime_info["run_cqlf_query"] = {
                "read_only": True,
                "concurrency_safe": True,
            }
            with patch.object(
                SessionManager,
                "_lm_summary",
                return_value="zusammenfassung der bisherigen schritte",
            ):
                orch.run("Zeig mir die KWIC für fox")
            ops = [json.loads(op) for op in project.timeline()]
            has_tool = any(op.get("tool") == "run_cqlf_query" for op in ops)
            has_summary = any("summary" in op for op in ops)
            self.assertTrue(has_tool)
            self.assertTrue(has_summary)


if __name__ == "__main__":
    unittest.main()
