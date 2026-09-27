from candyconc.tooling.registry import REGISTRY, llm_tool, get_schema_map


def test_get_schema_map_returns_expected():
    backup = list(REGISTRY)
    REGISTRY.clear()

    @llm_tool(
        {
            "type": "function",
            "function": {
                "name": "dummy_helper",
                "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
            },
        }
    )
    def dummy_helper(x: int) -> dict:
        return {"x": x}

    schemas = get_schema_map()
    assert schemas["dummy_helper"] == {"type": "object", "properties": {"x": {"type": "number"}}}

    REGISTRY[:] = backup
