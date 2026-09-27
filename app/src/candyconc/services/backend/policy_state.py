from __future__ import annotations

from typing import Dict, List

# Shared policy defaults for chat and MCP tool access, plus project quotas.
# PolicyEngine.check counts tool argument characters through _ra_tool_tokens,
# not output tokens. The allowance supports multi-step register comparisons
# while retaining an emergency stop for repeated tool calls.
POLICY_BUDGETS: Dict[str, int] = {"default": 200_000}
POLICY_ACLS: Dict[str, List[str]] = {}
PROJECT_QUOTAS: Dict[str, int] = {}
