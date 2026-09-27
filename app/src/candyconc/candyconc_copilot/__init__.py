import json
import logging
import asyncio
from typing import Any, Dict, List, TYPE_CHECKING

from candyconc.config import APP_CONFIG

from candyconc.tooling import get_tools, response_contract_for_prompt, select_tools_for_prompt

# Avoid heavy imports at module load time to prevent circular dependencies
# during test collection.  These classes are lazily imported via
# ``__getattr__`` below so that the rest of the module can be used without
# pulling in the full orchestrator stack.
if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from .orchestrator import ReActOrchestrator, State
    from .session_manager import SessionManager

from candyconc.core import query_runtime
from .cql_validation import validate
from .analysis import (
    collocate_stats,
    word_sketch,
    dispersion_offsets,
    keyness,
    frequency_list,
    semantic_search,
    run_cqlf_query,
)

run_query = query_runtime.run_query

LOGGER = logging.getLogger(__name__)

__all__ = [
    "generate",
    "validate",
    "analyse",
    "analyse_llm",
    "chat",
    "run_cqlf_query",
    "collocate_stats",
    "word_sketch",
    "dispersion_offsets",
    "keyness",
    "frequency_list",
    "semantic_search",
    "scientific_agent",
    "ReActOrchestrator",
    "State",
    "SessionManager",
]

# Integration tests update this counter to track validation false positives
FALSE_POSITIVES = 0

# Configuration for the language model server. ``COPILOT_ENDPOINT`` must point
# to an OpenAI compatible endpoint.  Calls to the copilot will raise
# ``RuntimeError`` if the value is missing.
#
# ``_LM_ENDPOINT`` und ``_LM_MODEL`` waren hier Modulkonstanten, an die
# IMPORTZEIT gebunden. Wer den Modellweg zur Laufzeit umstellte, aenderte
# ``APP_CONFIG``, und diese beiden Namen zeigten weiter auf den alten Wert.
# Sie werden deshalb in ``__getattr__`` bei jedem Zugriff frisch gelesen und
# ABSICHTLICH NICHT in ``globals()`` zwischengespeichert, denn genau das waere
# dieselbe Falle einen Zugriff spaeter.

# Tool definition for running CQLF queries via the local concordancer.
KWIC_TOOL = {
    "type": "function",
    "function": {
        "name": "run_cqlf_query",
        "description": (
            "Execute a CQLF query against the active corpus and return KWIC rows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "CQLF query string"},
                "ctx": {
                    "type": "integer",
                    "description": "Context tokens to either side of the match",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}









def generate(prompt: str) -> str:
    """Generate a CQLF query string from a natural language prompt using the LLM."""
    if not _LM_ENDPOINT:
        raise RuntimeError("COPILOT_ENDPOINT not configured")

    msg = _lm_chat(
        [{"role": "user", "content": prompt}], tools=[KWIC_TOOL]
    )
    if isinstance(msg, dict) and msg.get("content"):
        cand = msg["content"].strip()
        if not validate(cand)["errors"]:
            return cand
    raise RuntimeError("Invalid response from LLM")


def analyse(query: str) -> dict:
    """Return simplified validation results for ``query``.

    The return value omits span information and contains only the
    ``errors`` and ``suggestions`` keys required by the GUI.
    """
    result = validate(query)
    suggestions = []
    hints = []
    for s in result.get("suggestions", []):
        if isinstance(s, dict):
            suggestions.append(s.get("text", ""))
            hints.append(s.get("hint", ""))
        else:
            suggestions.append(s)
    return {
        "errors": result.get("errors", []),
        "suggestions": suggestions,
        "hints": hints,
    }


def analyse_llm(query: str) -> dict:
    """Use the LLM to analyse ``query`` and return JSON suggestions."""
    msg = _lm_chat(
        [
            {
                "role": "system",
                "content": (
                    "Return JSON with keys 'errors' and 'suggestions' for the given CQLF query."  # noqa: E501
                ),
            },
            {"role": "user", "content": query},
        ],
        tools=[],
    )
    text = msg.get("content", "") if isinstance(msg, dict) else ""
    try:
        data = json.loads(text)
    except Exception as exc:  # pragma: no cover - unexpected response
        raise RuntimeError("Invalid response from LLM") from exc
    if not isinstance(data, dict):  # pragma: no cover - unexpected structure
        raise RuntimeError("Invalid response from LLM")
    return data


def _lm_chat(
    messages: List[Dict[str, str]], *, tools: List[Dict[str, Any]] | None = None, json_schema: Dict[str, Any] | None = None
) -> Dict[str, str]:
    """Interact with the local language model, executing tools via the orchestrator."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no running loop
        return asyncio.run(_lm_chat_async(messages, tools=tools, json_schema=json_schema))
    else:  # pragma: no cover - running loop
        raise RuntimeError(
            "LM Chat im laufenden Event Loop aufgerufen. "
            "Bitte _lm_chat_async verwenden."
        )


async def _lm_chat_async(
    messages: List[Dict[str, str]], *, tools: List[Dict[str, Any]] | None = None, json_schema: Dict[str, Any] | None = None
) -> Dict[str, str]:
    """Async helper forwarding ``messages`` to the LLM via :class:`ReActOrchestrator`."""

    from .orchestrator import ReActOrchestrator
    from .session_manager import SessionManager
    from candyconc.services.llm_client import call_llm_async

    if tools is None:
        tools = get_tools()

    if not tools:
        resp = await call_llm_async(messages, tools, json_schema=json_schema)
        return resp["choices"][0]["message"]

    session = SessionManager()
    for m in messages[:-1]:
        session.append(m)
    last = messages[-1]
    role = last.get("role", "user")
    question = last.get("content", "")
    ui_context = response_contract_for_prompt(question) or {}
    tools = select_tools_for_prompt(question, list(tools), ui_context=ui_context)

    async def _call_llm(msgs: List[Dict[str, str]], t: List[Dict[str, Any]], *, stream: bool = False, user: str = "default", policy=None):
        return await call_llm_async(msgs, t, json_schema=json_schema, stream=stream, user=user, policy=policy)

    orch = ReActOrchestrator(tools, _call_llm, dispatch, session=session, ui_context=ui_context)
    content = await orch.run_async(question, role)
    return {"role": "assistant", "content": content}


async def chat(messages: List[Dict[str, str]], *, json_schema: Dict[str, Any] | None = None) -> Dict[str, str]:
    """Return an assistant reply for ``messages``.

    The conversation is forwarded to the endpoint specified via
    ``COPILOT_ENDPOINT`` using the OpenAI compatible API.  If the variable is
    not set or the request fails, a ``RuntimeError`` is raised.
    """

    if not _LM_ENDPOINT:
        raise RuntimeError("COPILOT_ENDPOINT not configured")

    return await _lm_chat_async(list(messages), json_schema=json_schema)


def _plan_scientific_tasks(question: str) -> tuple[str, list[str]]:
    """Return ``term`` and list of tasks inferred from ``question``."""

    if not _LM_ENDPOINT:
        raise RuntimeError("COPILOT_ENDPOINT not configured")

    prompt = (
        "Plan analysis steps for the question and return JSON with 'term' and "
        "a list 'tasks': " + question
    )
    msg = _lm_chat([{"role": "user", "content": prompt}], tools=[KWIC_TOOL])
    data = json.loads(msg.get("content", "{}"))
    term = str(data.get("term", "")).strip()
    tasks = [str(t).lower() for t in data.get("tasks", [])]
    if not term or not tasks:
        raise RuntimeError("Invalid plan from LLM")
    return term.lower(), tasks


def scientific_agent(question: str) -> str:
    """Execute a minimal multi-step analysis for ``question``.

    The implementation relies on :func:`run_query` and
    :func:`collocate_stats` to obtain the data required for answering the
    research question.  The agent first determines the analysis plan via
    :func:`_plan_scientific_tasks` and then executes each step in sequence,
    feeding the results from one step into the next when appropriate.
    """

    term, tasks = _plan_scientific_tasks(question)

    count = 0
    top_coll = ""

    for task in tasks:
        if task == "frequency":
            count = len(list(run_query(term)))
        elif task == "collocates":
            coll_df = collocate_stats(term)
            if not coll_df.empty:
                top_coll = coll_df["word"].iloc[0]

    parts = [f"'{term}' occurs {count} time{'s' if count != 1 else ''}."]
    if top_coll:
        parts.append(f"Top collocate: {top_coll}.")
    return " ".join(parts)


# Import tool wrappers after function definitions to avoid circular imports
from .tool_wrappers import (  # noqa: F401,E402
    RUN_CQLF_TOOL as RUN_CQLF_TOOL,
    COLLOCATE_TOOL as COLLOCATE_TOOL,
    FREQUENCY_TOOL as FREQUENCY_TOOL,
    WORD_SKETCH_TOOL as WORD_SKETCH_TOOL,
    run_cqlf_query_tool as run_cqlf_query_tool,
    collocate_stats_tool as collocate_stats_tool,
    word_sketch_tool as word_sketch_tool,
    frequency_list_tool as frequency_list_tool,
)  # noqa: F401,E402
from .dispatcher import dispatch as dispatch  # noqa: E402,F401

__all__.extend(
    [
        "run_cqlf_query_tool",
        "collocate_stats_tool",
        "word_sketch_tool",
        "frequency_list_tool",
        "RUN_CQLF_TOOL",
        "COLLOCATE_TOOL",
        "WORD_SKETCH_TOOL",
        "FREQUENCY_TOOL",
        "dispatch",
    ]
)

def __getattr__(name: str):
    """Lazy attribute loader for heavy submodules and live model settings."""
    if name == "_LM_ENDPOINT":
        return APP_CONFIG.COPILOT_ENDPOINT
    if name == "_LM_MODEL":
        return APP_CONFIG.COPILOT_MODEL
    if name in {"ReActOrchestrator", "State"}:  # pragma: no cover - import lazily
        from .orchestrator import ReActOrchestrator, State
        globals()["ReActOrchestrator"] = ReActOrchestrator
        globals()["State"] = State
        return globals()[name]
    if name == "SessionManager":
        from .session_manager import SessionManager
        globals()["SessionManager"] = SessionManager
        return SessionManager
    raise AttributeError(name)
