from __future__ import annotations
from candyconc.core.meta_filters import EingabeFormFehler

import functools
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, Annotated

from anyio import to_thread
from fastapi import FastAPI, HTTPException, Depends
from jsonschema import ValidationError, validate as json_validate

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, lt
from candyconc.capabilities.product import (
    COPILOT_TURN_CONTROL_TOOLS,
    ProductCopilotToolOperationBinding,
    visible_product_copilot_tools,
)
from candyconc.services.backend import auth
from candyconc.services.backend.policy_state import POLICY_ACLS
from candyconc.tooling.tool_selection import (
    bindings_allow_default_release_dispatch,
    is_tool_dispatchable_for_principal,
    product_binding_metadata,
    product_tool_bindings_by_name,
)


logger = logging.getLogger(__name__)

router = CandyAPIRouter()


def _load_tools() -> None:
    import candyconc.tooling  # noqa: F401


def _tool_tables() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    from candyconc.tooling.registry import (
        get_tools,
        get_schema_map,
        get_tool_runtime_info,
        REGISTRY,
    )

    _load_tools()
    tools = get_tools()
    schema_map = get_schema_map()
    runtime_info = get_tool_runtime_info()
    # Use REGISTRY (not get_tools) for callables - get_tools strips them
    funcs = {t["function"]["name"]: t.get("callable") for t in REGISTRY}
    response_schemas = {
        t["function"]["name"]: t.get("response_schema") for t in REGISTRY
    }
    return tools, schema_map, {
        "funcs": funcs,
        "responses": response_schemas,
        "runtime": runtime_info,
    }


def _strip_callables(tool: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(tool)
    cleaned.pop("callable", None)
    return cleaned


def _strict_arg_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with the top-level arg object closed to unknown keys.

    COPILOT-STRAY-ARG-500: an LLM may hallucinate an extra tool argument. Without
    ``additionalProperties: false`` the unexpected kwarg passes JSON validation,
    reaches ``func(**args)`` as an unexpected keyword argument, and the resulting
    ``TypeError`` becomes a 500. Closing the top-level object here — the ONE
    validation seam every tool passes through — rejects the stray arg as a clean
    400 for ALL tools (only ``frequency_list`` declared this inline before). Only
    the TOP-LEVEL args object is closed; nested free-form maps (``pos_map``,
    ``filters``, ``meta_filters``) keep their own ``additionalProperties`` so they
    are untouched. A schema that already sets ``additionalProperties`` is honoured
    as-is.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return schema
    if "additionalProperties" in schema:
        return schema
    return {**schema, "additionalProperties": False}


def _product_tool_bindings() -> dict[str, tuple[ProductCopilotToolOperationBinding, ...]]:
    return product_tool_bindings_by_name(visible_only=True)


def _is_product_tool_visible(name: str) -> bool:
    return bool(_product_tool_bindings().get(name))


def _bindings_for_tool(name: str) -> tuple[ProductCopilotToolOperationBinding, ...]:
    return _product_tool_bindings().get(name, ())


def _select_bindings(
    name: str,
    operation_id: str | None,
) -> tuple[ProductCopilotToolOperationBinding, ...]:
    bindings = _bindings_for_tool(name)
    if not operation_id:
        return bindings
    selected = tuple(binding for binding in bindings if binding.operation_id == operation_id)
    if not selected:
        raise HTTPException(
            status_code=403,
            detail="Tool is not bound to requested ProductOperation",
        )
    return selected


def _bindings_allow_default_release_dispatch(
    bindings: tuple[ProductCopilotToolOperationBinding, ...],
) -> bool:
    return bindings_allow_default_release_dispatch(bindings)


def _binding_metadata(
    bindings: tuple[ProductCopilotToolOperationBinding, ...],
) -> dict[str, Any]:
    return product_binding_metadata(bindings)


def _required_corpus_features(
    bindings: tuple[ProductCopilotToolOperationBinding, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                feature
                for binding in bindings
                for feature in binding.route.requires_corpus_features
            }
        )
    )


def _corpus_name_from_args(args: dict[str, Any]) -> str | None:
    for key in ("corpus", "corpus_name", "corpusId", "corpus_id"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _corpus_summary_for_mcp_call(args: dict[str, Any]) -> dict[str, Any]:
    from candyconc.services.backend.corpus_registry_service import CorpusRegistryService

    from candyconc.services.backend import server as _server

    default_path = _server._INDEX_PATH
    if default_path is None:
        try:
            default_path = _server._configured_default_index_path()
        except Exception:
            default_path = None
    service = CorpusRegistryService(_server._CORPUS_DIR, default_path)
    corpus_name = _corpus_name_from_args(args)
    if corpus_name:
        return service.inspect(corpus_name)
    # Without a ``corpus`` argument the tools resolve via ``get_index()``,
    # whose precedence is env > config > registry
    # (server.aktivierung_wirkungslos). Taking the registry entry marked
    # active here would check the features of a DIFFERENT corpus than the
    # one being computed on. With an index pin set the two diverge: word_sketch
    # would be refused for an index that HAS dependency relations, because
    # the registry corpus lacks token_attributes.rel. An error that denies
    # the corpus a property it has is costlier than a missing check: it
    # sounds like a finding about the data.
    wirksamer_pfad = _server._INDEX_PATH
    if wirksamer_pfad is None:
        try:
            wirksamer_pfad = _server._resolve_index_path()
        except Exception:
            wirksamer_pfad = None
    if wirksamer_pfad is not None:
        ziel = Path(wirksamer_pfad).expanduser().resolve(strict=False)
        for eintrag in service.list_corpora():
            roh = eintrag.get("path")
            if not roh:
                continue
            if Path(str(roh)).expanduser().resolve(strict=False) == ziel:
                return eintrag
    active = next(
        (
            item
            for item in service.list_corpora()
            if item.get("active") and item.get("status", "ready") == "ready"
        ),
        None,
    )
    if active is not None:
        return active
    return service.inspect("default")


def _feature_available(summary: dict[str, Any], requirement: str) -> bool:
    features = summary.get("features")
    if not isinstance(features, dict):
        return False
    parts = [part for part in requirement.split(".") if part]
    if len(parts) < 2:
        return False
    if parts[0] == "token_attributes":
        return any(
            isinstance(item, dict)
            and (item.get("id") == parts[1] or item.get("cql_attribute") == parts[1])
            for item in features.get("token_attributes", [])
        )
    if parts[0] == "frequency_groups":
        return any(
            isinstance(item, dict) and item.get("id") == parts[1]
            for item in features.get("frequency_groups", [])
        )
    current: Any = features
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return bool(current)


def _enforce_corpus_feature_gates(
    args: dict[str, Any],
    bindings: tuple[ProductCopilotToolOperationBinding, ...],
) -> None:
    required = _required_corpus_features(bindings)
    if not required:
        return
    try:
        summary = _corpus_summary_for_mcp_call(args)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except Exception as exc:
        raise ApiError(
            409,
            "tool.corpus_features_unchecked",
            lt(
                "Korpusfeatures konnten nicht geprüft werden: {error}",
                "Corpus features could not be checked: {error}",
            ),
            error=exception_text(exc),
        ) from exc
    missing = [feature for feature in required if not _feature_available(summary, feature)]
    if missing:
        corpus = summary.get("name") or _corpus_name_from_args(args) or "default"
        raise HTTPException(
            status_code=409,
            detail={
                "error": "missing_corpus_features",
                "corpus": corpus,
                "missing": missing,
                "message": lt(
                    "Tool ist für dieses Korpus laut ProductOperation-"
                    "Feature-Gate nicht anwendbar: {missing}",
                    "According to the ProductOperation feature gate, the tool "
                    "does not apply to this corpus: {missing}",
                ).format(missing=", ".join(missing)),
            },
        )


def _with_runtime_metadata(
    tool: dict[str, Any], runtime_info: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    cleaned = _strip_callables(tool)
    name = str(cleaned.get("function", {}).get("name", "") or "")
    info = runtime_info.get(name)
    if info is None:
        # Missing runtime metadata is not evidence of read-only safety. Surface it
        # fail-safe so clients cannot treat an unclassified tool as safe.
        cleaned["read_only"] = False
        cleaned["concurrency_safe"] = False
        cleaned["runtime_metadata_status"] = "missing"
        return cleaned
    cleaned["read_only"] = bool(info.get("read_only", False))
    cleaned["concurrency_safe"] = bool(info.get("concurrency_safe", False))
    cleaned["runtime_metadata_status"] = "verified"
    cleaned.update(_binding_metadata(_bindings_for_tool(name)))
    return cleaned


def _product_tool_status(
    name: str,
    *,
    registered_tool_names: set[str],
    runtime_info: dict[str, dict[str, Any]],
    allowed: list[str] | None,
) -> dict[str, Any]:
    bindings = _bindings_for_tool(name)
    visible_product_tools = visible_product_copilot_tools()
    visible_product_claimed = name in visible_product_tools
    registered = name in registered_tool_names
    info = runtime_info.get(name)
    runtime_metadata_status = "verified" if info is not None else "missing"
    read_only = bool(info.get("read_only", False)) if info is not None else False
    concurrency_safe = bool(info.get("concurrency_safe", False)) if info is not None else False
    metadata = _binding_metadata(bindings) if bindings else {
        "product_operation_ids": [],
        "product_capability_ids": [],
        "product_effects": [],
        "requires_corpus_features": [],
    }

    status = "operation_bound"
    reason = lt(
        "Tool ist registriert, runtime-klassifiziert und an ProductOperations gebunden.",
        "The tool is registered, classified at runtime and bound to ProductOperations.",
    )
    dispatchable = True
    if name in COPILOT_TURN_CONTROL_TOOLS:
        # Turn control is protocol, not a product operation: it needs no
        # binding, and the dispatch guard checks only runtime metadata and the
        # session ACL (tool_selection.is_tool_dispatchable_for_principal).
        status = "turn_control"
        reason = lt(
            "Steuerwerkzeug: beendet die Werkzeugphase des Copiloten, liefert keine Korpus-Evidenz.",
            "Control tool: ends the copilot's tool phase and returns no corpus evidence.",
        )
        dispatchable = registered and info is not None and (allowed is None or name in allowed)
        return {
            "name": name,
            "status": status,
            "dispatchable": dispatchable,
            "reason": reason,
            "registered": registered,
            "visible_product_claimed": False,
            "read_only": read_only,
            "concurrency_safe": concurrency_safe,
            "runtime_metadata_status": runtime_metadata_status,
            "role": "turn_control",
            **metadata,
        }
    if not registered:
        status = "registry_missing"
        reason = lt(
            "Tool ist im Product-Capability-Contract sichtbar, aber nicht in der MCP-Registry registriert.",
            "The tool is visible in the product capability contract but not registered in the MCP registry.",
        )
        dispatchable = False
    elif not bindings:
        status = "capability_only" if visible_product_claimed else "unclaimed_registered"
        reason = lt(
            "Tool ist im sichtbaren Product-Contract nur capability-level deklariert; "
            "MCP-Dispatch braucht eine konkrete ProductOperation-Bindung.",
            "The tool is declared only at capability level in the visible product contract. "
            "MCP dispatch needs a concrete ProductOperation binding.",
        ) if visible_product_claimed else lt(
            "Tool ist in der MCP-Registry registriert, aber keiner sichtbaren ProductOperation zugeordnet.",
            "The tool is registered in the MCP registry but not assigned to any visible ProductOperation.",
        )
        dispatchable = False
    elif info is None:
        status = "metadata_missing"
        reason = lt(
            "Tool ist ProductOperation-gebunden, aber Runtime-Sicherheitsmetadaten fehlen.",
            "The tool is bound to a ProductOperation, but runtime safety metadata is missing.",
        )
        dispatchable = False
    elif allowed is not None and name not in allowed:
        status = "policy_blocked"
        reason = lt(
            "Tool ist nicht in der aktuellen Tool-ACL der Session freigegeben.",
            "The tool is not allowed by the current tool ACL of the session.",
        )
        dispatchable = False
    elif allowed is None and auth.is_release_mode() and not read_only:
        status = "policy_blocked"
        reason = lt(
            "Release-Default-Deny blockiert nicht-read-only Tools ohne explizite Tool-ACL.",
            "Release default deny blocks tools that are not read-only when no explicit tool ACL is set.",
        )
        dispatchable = False
    elif allowed is None and auth.is_release_mode() and not _bindings_allow_default_release_dispatch(bindings):
        status = "policy_blocked"
        reason = lt(
            "ProductOperation-Effekte benötigen eine explizite Tool-ACL.",
            "ProductOperation effects need an explicit tool ACL.",
        )
        dispatchable = False

    return {
        "name": name,
        "status": status,
        "dispatchable": dispatchable,
        "reason": reason,
        "registered": registered,
        "visible_product_claimed": visible_product_claimed,
        "read_only": read_only,
        "concurrency_safe": concurrency_safe,
        "runtime_metadata_status": runtime_metadata_status,
        **metadata,
    }


def _product_tool_statuses(
    tools: list[dict[str, Any]],
    runtime_info: dict[str, dict[str, Any]],
    allowed: list[str] | None,
) -> list[dict[str, Any]]:
    registered_tool_names = {
        str(tool.get("function", {}).get("name", "") or "")
        for tool in tools
        if tool.get("function", {}).get("name")
    }
    status_names = registered_tool_names | set(visible_product_copilot_tools())
    return [
        _product_tool_status(
            name,
            registered_tool_names=registered_tool_names,
            runtime_info=runtime_info,
            allowed=allowed,
        )
        for name in sorted(status_names)
    ]


def _runtime_info_for_tool(name: str, runtime_info: dict[str, dict[str, Any]]) -> dict[str, Any]:
    info = runtime_info.get(name)
    if info is None:
        raise HTTPException(
            status_code=500,
            detail=f"Tool {name} has no runtime safety metadata",
        )
    return info


def _is_tool_dispatchable_for_principal(
    name: str,
    runtime_info: dict[str, dict[str, Any]],
    allowed: list[str] | None,
) -> bool:
    return is_tool_dispatchable_for_principal(
        name,
        runtime_info=runtime_info,
        allowed_tools=allowed,
        release_mode=auth.is_release_mode(),
        bindings_by_tool=_product_tool_bindings(),
    )


@router.get("/tools")
async def list_tools(
    _token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    tools, _, tables = _tool_tables()
    all_tools = list(tools)
    user = auth.username_for_token(_token)
    allowed = POLICY_ACLS.get(user) if user else None
    if allowed is not None:
        tools = [t for t in tools if t.get("function", {}).get("name") in allowed]
    tools = [
        t
        for t in tools
        if _is_tool_dispatchable_for_principal(
            str(t.get("function", {}).get("name", "") or ""),
            tables["runtime"],
            allowed,
        )
    ]
    return {
        "tools": [_with_runtime_metadata(t, tables["runtime"]) for t in tools],
        "tool_statuses": _product_tool_statuses(all_tools, tables["runtime"], allowed),
    }


@router.post("/call")
async def call_tool(
    payload: Dict[str, Any],
    _token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    return await execute_tool_call(payload, _token)


async def execute_tool_call(
    payload: Dict[str, Any],
    _token: str | None,
) -> Dict[str, Any]:
    """Validate, gate and execute one tool call (shared seam).

    Byte-identische Gate-Kette der HTTP-Route ``POST /mcp/call``
    (Schema-Validierung inkl. ``_strict_arg_schema``, ACL/PolicyEngine,
    Release-Default-Deny, ProductOperation-Bindung, Corpus-Feature-Gates,
    Response-Schema-Pruefung). Der In-Process-Dispatcher
    (``candyconc_copilot.dispatcher``) ruft diese Funktion DIREKT auf, damit
    Tool-Roundtrips keinen HTTP-Selbstaufruf mehr brauchen. Fehler werden
    weiterhin als ``HTTPException`` signalisiert, der Dispatcher bildet sie
    auf die bisherige Transport-Fehlersemantik ab. Die 401-Pruefung unten
    ersetzt fuer den In-Process-Weg die ``require_role("user")``-Dependency
    der Route (identisches Verhalten bei aktivem RBAC).
    """
    name = payload.get("name") or payload.get("tool")
    args = payload.get("arguments") or payload.get("params") or {}
    operation_id = payload.get("operation_id")
    if not name:
        raise HTTPException(status_code=400, detail="Missing tool name")
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="arguments must be object")
    if operation_id is not None and not isinstance(operation_id, str):
        raise HTTPException(status_code=400, detail="operation_id must be string")

    user = auth.username_for_token(_token)
    if user is None and auth.RBAC_ENABLED:
        raise HTTPException(status_code=401, detail="Unauthorized")
    allowed = None
    if user:
        allowed = POLICY_ACLS.get(user)
        if allowed is not None and name not in allowed:
            raise HTTPException(status_code=403, detail="Permission denied")

    _tools, schema_map, tables = _tool_tables()
    funcs = tables["funcs"]
    responses = tables["responses"]
    runtime_info = tables["runtime"]

    if name not in schema_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool {name}")
    # Turn control is not product surface, but the copilot may call it.
    # Without this exemption a submission with full content runs into a 403
    # at exactly this check. The same exemption as in tool_selection, the
    # capability contract itself does not grow.
    from candyconc.tooling.tool_selection import ist_turn_steuerung

    if not _is_product_tool_visible(str(name)) and not ist_turn_steuerung(str(name)):
        raise HTTPException(status_code=403, detail="Tool is not visible in Product-Capability-Contract")
    selected_bindings = _select_bindings(str(name), operation_id)

    tool_info = _runtime_info_for_tool(str(name), runtime_info)
    is_read_only = bool(tool_info.get("read_only", False))
    require_read_only = payload.get("require_read_only") is True
    if require_read_only and not is_read_only:
        raise HTTPException(status_code=403, detail="Tool is not read-only")
    if allowed is None and auth.is_release_mode() and not is_read_only:
        raise HTTPException(
            status_code=403,
            detail=(
                "Permission denied: non-read-only tool blocked by release "
                "default-deny (no tool ACL configured)"
            ),
        )
    if (
        allowed is None
        and auth.is_release_mode()
        and not _bindings_allow_default_release_dispatch(selected_bindings)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Permission denied: ProductOperation effects require an "
                "explicit tool ACL"
            ),
        )

    try:
        json_validate(args, _strict_arg_schema(schema_map[name]))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid arguments: {exc.message}")
    _enforce_corpus_feature_gates(args, selected_bindings)

    func = funcs.get(name)
    if func is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool {name}")

    # Lazy import: tool_wrappers pulls in the whole copilot/engine stack, and
    # mcp_server is bound during backend.server init (a top-level import here
    # would re-enter a partially initialised module). Resolved per call instead.
    from candyconc.candyconc_copilot.tool_wrappers import (
        UnknownResourceError,
        ToolInputError,
    )

    try:
        if inspect.iscoroutinefunction(func):
            result = await func(**args)
        else:
            # anyio.to_thread.run_sync forwards only POSITIONAL args to the worker
            # thread; passing **args directly raises TypeError ("unexpected keyword
            # argument"). Bind the tool kwargs via functools.partial so every
            # parameterized tool dispatches correctly.
            result = await to_thread.run_sync(functools.partial(func, **args))
    except UnknownResourceError as exc:
        # COPILOT-3: the LLM asked for a corpus/docset that is unknown or not
        # loaded — a bad request, not an internal fault. Map it to a clean 404
        # (genuine engine/index failures fall through to the 500 below).
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except ToolInputError as exc:
        # COPILOT-KEYNESS-INCOMPLETE-500: the LLM supplied invalid / incomplete
        # arguments (e.g. only one half of a required target/reference pair).
        # That is a bad request, not an internal fault — map it to a clean 400
        # (genuine engine/index failures fall through to the 500 below).
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except EingabeFormFehler as exc:
        # Map invalid filter forms to input errors before the route catch-all
        # turns unknown exceptions into HTTP 500. This route intercepts errors
        # before the shared application handler can classify them.
        logger.info("%s: ungueltige Eingabeform: %s", name, exc)
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except Exception as exc:
        logger.error("%s failed: %s", name, exc)
        # Mit Typ: "63079" allein hielt das Modell fuer eine Tokenposition.
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: " + exception_text(exc))

    resp_schema = responses.get(name)
    if resp_schema is not None:
        try:
            json_validate(result, resp_schema)
        except ValidationError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid result: {exc.message}")

    # Dieselbe Naht wie im Orchestrator. Ein frueherer Commit hat
    # behauptet, sie sitze hier, und sie sass nicht hier: die Aenderung ist
    # nie im Baum angekommen. build_method_block fuehrt den Indexstand als
    # "<absoluter Pfad>@<mtime_ns>", und diese Route gibt die ROHE
    # Werkzeugausgabe an den Aufrufer.
    from candyconc.candyconc_copilot.analysis_grounding import (
        werkzeugausgabe_ohne_betreiberpfad,
    )

    return werkzeugausgabe_ohne_betreiberpfad(result)


app = FastAPI()
app.include_router(router)
