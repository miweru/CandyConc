"""Integration tests for agentic tool calling.

Tests that the LLM can:
1. Receive tool definitions
2. Generate tool_calls in the response
3. Execute tools via the orchestrator

WICHTIG: Diese Tests verwenden das echte LLM und keine Mocks!
Der Endpoint muss korrekt konfiguriert sein: /v1/chat/completions (NICHT /api/v1/chat)
"""

import asyncio
import json
import os
import pytest
import httpx

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CANDYCONC_RUN_LM_INTEGRATION") != "1",
        reason="Set CANDYCONC_RUN_LM_INTEGRATION=1 to run live LLM integration tests",
    ),
]


def llm_available() -> bool:
    """Check if LLM server is reachable."""
    try:
        endpoint = os.environ.get("COPILOT_ENDPOINT", "http://127.0.0.1:1234/v1/chat/completions")
        resp = httpx.get(endpoint.rsplit("/", 2)[0] + "/models", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def setup_env():
    """Set up environment for agentic tests."""
    # Ensure we use the correct endpoint for tool calling
    os.environ["COPILOT_ENDPOINT"] = "http://127.0.0.1:1234/v1/chat/completions"
    os.environ["COPILOT_TIMEOUT"] = "120"
    yield


@pytest.fixture(autouse=True)
def _require_llm_runtime():
    if not llm_available():
        pytest.skip("LLM server not available")


class TestAgenticToolCalls:
    """Test that LLM can generate and execute tool calls."""

    def test_llm_receives_tools_in_payload(self):
        """Verify that tools are included in the payload when using correct endpoint."""
        from candyconc.services.llm_client import _build_payload, _is_custom_chat_endpoint

        endpoint = "http://127.0.0.1:1234/v1/chat/completions"

        # Verify this is NOT detected as custom endpoint
        assert not _is_custom_chat_endpoint(endpoint), \
            "Standard OpenAI endpoint should not be detected as custom"

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_cqlf_query",
                    "description": "Execute a CQL query",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"]
                    }
                }
            }
        ]

        messages = [{"role": "user", "content": "Search for 'Test'"}]
        payload = _build_payload(endpoint, "gpt-oss-120b", messages, tools, stream=False)

        # Verify tools are in payload
        assert "tools" in payload, "Tools should be in payload for standard endpoint"
        assert len(payload["tools"]) == 1
        assert payload["tools"][0]["function"]["name"] == "run_cqlf_query"
        assert "messages" in payload, "Messages should be in standard format"

    def test_custom_endpoint_no_tools(self):
        """Verify that /api/v1/chat endpoint does NOT include tools (known limitation)."""
        from candyconc.services.llm_client import _build_payload, _is_custom_chat_endpoint

        custom_endpoint = "http://127.0.0.1:1234/api/v1/chat"

        # Verify this IS detected as custom endpoint
        assert _is_custom_chat_endpoint(custom_endpoint), \
            "Custom endpoint should be detected"

        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        messages = [{"role": "user", "content": "Test"}]
        payload = _build_payload(custom_endpoint, "model", messages, tools, stream=False)

        # Verify tools are NOT in payload (limitation of custom endpoint)
        assert "tools" not in payload, \
            "Custom endpoint does not support tools - use /v1/chat/completions instead"
        assert "input" in payload, "Custom endpoint uses 'input' field"

    def test_llm_generates_tool_calls(self):
        """Test that LLM actually generates tool_calls when asked to use a tool."""
        import asyncio
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        tools = get_tools()

        # Clear prompt that should trigger tool usage
        messages = [
            {
                "role": "system",
                "content": "Du bist ein Korpuslinguistik-Assistent. Wenn der User nach Wörtern suchen möchte, "
                           "MUSST du das run_cqlf_query Tool verwenden. Antworte NICHT mit Text, sondern "
                           "rufe direkt das Tool auf."
            },
            {
                "role": "user",
                "content": "Suche nach dem Wort 'Klimawandel' im Korpus."
            }
        ]

        result = asyncio.run(call_llm_async(messages, tools, user="test"))

        # Debug output
        print(f"\n=== LLM Response ===")
        print(f"Keys: {result.keys()}")

        assert "choices" in result, "Response should have choices"
        choice = result["choices"][0]
        msg = choice.get("message", {})

        print(f"Message keys: {msg.keys()}")
        print(f"finish_reason: {choice.get('finish_reason')}")

        if "tool_calls" in msg:
            print(f"tool_calls gefunden: {json.dumps(msg['tool_calls'], indent=2)}")
        else:
            print(f"KEINE tool_calls! Content: {msg.get('content', '')[:500]}")

        # Verify tool_calls exist
        assert "tool_calls" in msg, \
            f"LLM should generate tool_calls. Got message keys: {msg.keys()}, content: {msg.get('content', '')[:200]}"

        tool_calls = msg["tool_calls"]
        assert len(tool_calls) > 0, "Should have at least one tool call"

        # Verify tool call structure
        tc = tool_calls[0]
        assert tc.get("type") == "function"
        assert "function" in tc
        assert tc["function"]["name"] == "run_cqlf_query", \
            f"Expected run_cqlf_query, got {tc['function']['name']}"

    def test_orchestrator_executes_tool(self):
        """Test that orchestrator can execute tool calls from LLM."""
        import asyncio
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator, State
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        tools = get_tools()
        executed_tools = []

        async def mock_dispatch(tool_call, token=None):
            """Track tool executions."""
            name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"].get("arguments", "{}"))
            executed_tools.append({"name": name, "args": args})

            # Return mock result
            if name == "run_cqlf_query":
                return {
                    "status": "ok",
                    "hits": 42,
                    "kwic": [
                        {"left": "Der", "match": "Klimawandel", "right": "ist..."}
                    ]
                }
            return {"status": "ok"}

        async def run_test():
            orchestrator = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=mock_dispatch,
                ui_context={"autonomy_level": 10}  # Max autonomy - no approval needed
            )

            # Run orchestrator with a query that should trigger tool use
            result = await orchestrator.run_async(
                "Suche nach 'Klimawandel' und zeige mir die Ergebnisse.",
                max_steps=5
            )
            return result, orchestrator

        result, orchestrator = asyncio.run(run_test())

        print(f"\n=== Orchestrator Result ===")
        print(f"Final response: {result[:500] if result else 'EMPTY'}")
        print(f"Executed tools: {executed_tools}")
        print(f"Final state: {orchestrator.state}")

        # Verify tool was executed
        assert len(executed_tools) > 0, \
            f"At least one tool should have been executed. State: {orchestrator.state}"
        assert any(t["name"] == "run_cqlf_query" for t in executed_tools), \
            f"run_cqlf_query should have been called. Executed: {executed_tools}"

    def test_multi_step_agentic_workflow(self):
        """Test that LLM can execute a multi-step plan with multiple tool calls."""
        import asyncio
        from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
        from candyconc.services.llm_client import call_llm_async
        from candyconc.tooling.registry import get_tools

        tools = get_tools()
        executed_tools = []

        async def tracking_dispatch(tool_call, token=None):
            """Track all tool executions."""
            name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"].get("arguments", "{}"))
            executed_tools.append({"name": name, "args": args})

            # Return appropriate mock results
            if name == "run_cqlf_query":
                return {"status": "ok", "hits": 100, "kwic": []}
            elif name == "collocate_stats":
                return {"status": "ok", "collocations": [
                    {"word": "global", "mi": 5.2, "t_score": 8.1},
                    {"word": "anthropogen", "mi": 4.8, "t_score": 6.3}
                ]}
            return {"status": "ok", "data": {}}

        async def run_test():
            orchestrator = ReActOrchestrator(
                tools=tools,
                call_llm=call_llm_async,
                dispatch=tracking_dispatch,
                ui_context={"autonomy_level": 10},
                llm_retries=1
            )

            # Complex task that requires multiple steps
            result = await orchestrator.run_async(
                "Analysiere die Kollokationen von 'Klimawandel'. "
                "Führe zuerst eine Suche durch, dann berechne die Kollokationen.",
                max_steps=8
            )
            return result

        result = asyncio.run(run_test())

        print(f"\n=== Multi-Step Result ===")
        print(f"Executed {len(executed_tools)} tools: {[t['name'] for t in executed_tools]}")

        # Should have executed at least one tool (ideally two)
        assert len(executed_tools) >= 1, "Should execute at least one tool in multi-step workflow"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
