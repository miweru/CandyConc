from candyconc.tooling.registry import REGISTRY, get_tools, llm_tool


def test_llm_tool_registers_function():
    # Real contract (src/candyconc/tooling/registry.py, get_tools): the
    # REGISTRY entry keeps the decorated callable, while get_tools() returns
    # only the JSON-serializable surface ("ohne callable/response_schema").
    # Asserting a "callable" key on get_tools() output was testing a contract
    # that never existed.
    backup = list(REGISTRY)
    REGISTRY.clear()
    try:

        @llm_tool(
            {
                "type": "function",
                "function": {
                    "name": "dummy_tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )
        def dummy_tool():
            return {"status": "success"}

        assert any(entry.get("callable") is dummy_tool for entry in REGISTRY)

        tools = get_tools()
        assert [t["function"]["name"] for t in tools] == ["dummy_tool"]
        assert all("callable" not in t for t in tools)
    finally:
        # try/finally: a failing assertion must not leak the cleared/mutated
        # REGISTRY into later tests (it previously left only "dummy_tool"
        # registered, cascading failures through the rest of tests/tooling).
        REGISTRY[:] = backup
