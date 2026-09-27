"""The capability contract names the copilot's turn-control tools.

Regression: ``deutung_abgeben`` ended every copilot turn, the backend
processed it, but the UI showed it red as "Tool gesperrt". The contract knew
no such tool, and the MCP tool status reported it as ``unclaimed_registered``
and not dispatchable, although the dispatch guard lets it through
(``tool_selection._TURN_STEUERUNG_TOOLS``). The contract now carries the one
list, the tool selection and the MCP status read it.
"""

from __future__ import annotations


def test_contract_lists_turn_control_tools():
    from candyconc.capabilities.product import build_product_capability_contract

    contract = build_product_capability_contract()
    tools = {t["name"]: t for t in contract["copilot_control_tools"]}
    assert tools["deutung_abgeben"]["role"] == "turn_control"
    assert tools["deutung_abgeben"]["label"]
    assert tools["deutung_abgeben"]["description"]


def test_contract_route_keeps_the_field():
    from candyconc.capabilities.product import build_product_capability_contract
    from candyconc.services.backend.schemas import ProductCapabilityContractResponse

    payload = ProductCapabilityContractResponse(**build_product_capability_contract()).model_dump()
    assert [t["name"] for t in payload["copilot_control_tools"]] == ["deutung_abgeben"]


def test_tool_selection_reads_the_contract_list():
    from candyconc.capabilities.product import COPILOT_TURN_CONTROL_TOOLS
    from candyconc.tooling.tool_selection import _TURN_STEUERUNG_TOOLS, ist_turn_steuerung

    assert _TURN_STEUERUNG_TOOLS == COPILOT_TURN_CONTROL_TOOLS
    assert ist_turn_steuerung("deutung_abgeben")


def test_mcp_status_reports_turn_control_as_dispatchable():
    from candyconc.services import mcp_server

    status = mcp_server._product_tool_status(
        "deutung_abgeben",
        registered_tool_names={"deutung_abgeben"},
        runtime_info={"deutung_abgeben": {"read_only": True, "concurrency_safe": True}},
        allowed=None,
    )
    assert status["status"] == "turn_control"
    assert status["role"] == "turn_control"
    assert status["dispatchable"] is True
    blocked = mcp_server._product_tool_status(
        "deutung_abgeben",
        registered_tool_names={"deutung_abgeben"},
        runtime_info={"deutung_abgeben": {"read_only": True}},
        allowed=["run_cqlf_query"],
    )
    assert blocked["dispatchable"] is False
