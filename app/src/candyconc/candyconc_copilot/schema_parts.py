# -*- coding: utf-8 -*-
"""Bausteine der Antwortschemata.

Ausgelagert aus ``tool_wrappers``, damit die Schemata dort stehen koennen,
wo der Aufrufvertrag des jeweiligen Werkzeugs steht (etwa
``keyness_tool_def``), ohne einen Ringschluss ueber die Fassade.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# F6: response_schema toolkit.
#
# Every @llm_tool below carries a response_schema built from the VERIFIED live
# return keys (probed on the bench index). This is the structural root fix for
# the documentation-drift / field-hallucination class: the schema is the single
# machine-checkable contract, and tests/integration/test_tool_surface_runtime.py
# asserts that each tool's real output stays a subset of its schema and that the
# advertised (required) fields actually appear. Row objects use
# additionalProperties:false so a stray engine column is caught immediately.
#
# ``_obj`` builds an object schema; ``_rows`` builds the {status, rows:[...]}
# shape shared by the table-returning tools.
# --------------------------------------------------------------------------- #
def _obj(
    properties: Dict[str, Any],
    *,
    required: Optional[List[str]] = None,
    additional: bool = False,
) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required is not None:
        schema["required"] = required
    return schema


def _str() -> Dict[str, Any]:
    return {"type": "string"}


def _num() -> Dict[str, Any]:
    return {"type": ["number", "integer", "null"]}


def _int() -> Dict[str, Any]:
    return {"type": ["integer", "null"]}


def _bool() -> Dict[str, Any]:
    return {"type": "boolean"}


def _row_schema(props: Dict[str, Any]) -> Dict[str, Any]:
    """A row object schema with additionalProperties:false (F6 row contract)."""
    return _obj(props, additional=False)


def _rows_response(
    row_props: Dict[str, Any],
    *,
    extra_top: Optional[Dict[str, Any]] = None,
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    props: Dict[str, Any] = {
        "status": _str(),
        "rows": {"type": "array", "items": _row_schema(row_props)},
    }
    if extra_top:
        props.update(extra_top)
    return _obj(props, required=required or ["status", "rows"])
