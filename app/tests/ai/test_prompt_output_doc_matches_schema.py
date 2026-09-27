"""DT-PROMPTS-DRIFT: keep the prompt's TOOLS_DOC OUTPUT block honest.

The system prompt advertises a second, human-written documentation surface for
every tool's output shape (TOOLS_DOC). It must NOT drift from the machine-checked
``response_schema`` attached to each ``@llm_tool``. This unit test (no index
needed) asserts, per registered tool, that every top-level + row property the
schema declares actually appears in the TOOLS_DOC block — so an advertised OUTPUT
field can never be undocumented prose, and a renamed field is caught here.

It also pins the grounding-critical prompt fixes:
- BEISPIEL 1 must NOT teach deriving a hit COUNT from run_cqlf_query rows; the
  worked example must use the COUNT tool (query_count) for "Wie oft kommt X vor?".
- METHOD_HINTS must route the count question to query_count, not run_cqlf_query /
  frequency_list.
- The similar_words doc must reflect the graceful status="unavailable" degrade,
  not the stale "RuntimeError ohne embeddings" claim.
"""

from __future__ import annotations

import importlib
import re
import sys

import pytest


def _load_real_tool_wrappers_and_registry():
    """Load the REAL tool_wrappers + registry (the top-level conftest stubs
    them), returning (registry_entries, prompts_module). Touched sys.modules
    entries are restored so no other test observes the swap."""
    touched = [
        "candyconc.tooling.registry",
        "candyconc.candyconc_copilot.tool_wrappers",
        "candyconc_copilot.tool_wrappers",
    ]
    saved = {name: sys.modules.get(name) for name in touched}
    had = {name: name in sys.modules for name in touched}
    try:
        sys.modules.pop("candyconc.tooling.registry", None)
        registry = importlib.import_module("candyconc.tooling.registry")
        sys.modules.pop("candyconc_copilot.tool_wrappers", None)
        importlib.import_module("candyconc_copilot.tool_wrappers")
        entries = list(registry.REGISTRY)
        return entries
    finally:
        for name in touched:
            if had[name]:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


_REGISTRY = _load_real_tool_wrappers_and_registry()

from candyconc.candyconc_copilot import prompts  # noqa: E402


# Schema property names that are intentionally NOT spelled out in prose because
# they are diagnostics/degrade-only envelopes the doc summarises generically.
_DOC_EXEMPT_KEYS = {
    "status",  # documented globally ("Alle Tools geben {status: success, ...}")
    "rows",
    "diagnostics",
    "meta",
    "fallback",
    "code",  # similar_words degrade-branch envelope
    "detail",  # not_applicable envelope
    "feature",  # not_applicable envelope
    "message",  # not_applicable envelope
    "reason",  # not_applicable / degrade envelope
    "backend",  # similar_words degrade-branch
    "clusters",
    "plan",
    "subcorpora",
    "tables",
    "values",
    "available_fields",
    "nodes",
    "edges",
    "neighbours",
    "groups",
    "variants",
    "offsets",
    "observed",
    "doc_sizes",
    "partitions",
    "label",  # informational
    "name",
    "source",
    "url",
    "input_token_count",  # semantic_cluster_words diagnostics envelope
    "cluster_token_count",  # semantic_cluster_words diagnostics envelope
    # Spacing flags of a KWIC row from an index with the original spacing
    # (whitespace_after.bin). The harness joins evidence lines with them, the
    # model reads left, kw and right. No analysis output of their own.
    "ws_before_kw",
    "ws_after_kw",
    # word_sketch discloses the applied reliability floor as a top-level scalar
    # (WS-COPILOT-NOFLOOR) — a disclosed-meta envelope, not a substantive output
    # column; the floor itself is documented in the tool description prose.
    "min_freq",
}


def _schema_property_names(schema: dict) -> set[str]:
    """Collect top-level + nested-row property names a schema declares.

    Subtrees rooted at an exempt key (e.g. ``diagnostics``) are NOT descended
    into: their inner fields are part of a summarised envelope, not advertised
    leaf OUTPUT fields, so they must not be required in the prose.
    """
    names: set[str] = set()

    def _walk(node) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            for key, sub in props.items():
                names.add(key)
                if key in _DOC_EXEMPT_KEYS:
                    continue  # do not descend into a summarised envelope
                _walk(sub)
        items = node.get("items")
        if isinstance(items, dict):
            _walk(items)
        addl = node.get("additionalProperties")
        if isinstance(addl, dict):
            _walk(addl)

    _walk(schema)
    return names


def _tools_doc_text() -> str:
    return prompts.TOOLS_DOC


def _tools_doc_blocks() -> dict[str, str]:
    """TOOLS_DOC nach Werkzeugbloecken, Blockanfang = die Signaturzeile.

    Gate 13: der Waechter prueft nicht mehr das GANZE Dokument. Er tat es,
    und war damit formal erfuellt und inhaltlich umgehbar: die neu
    deklarierten ``metric_units``-Schluessel von ``collocate_stats`` galten
    als dokumentiert, weil ``expected`` im keyness-Block stand und ``rank``
    als deutsches Verb ``rankt`` im Fliesstext. Gegenprobe des Pruefers:
    mit ENTFERNTEM ``metric_units,`` aus dem Block meldete die alte
    Waechterlogik weiterhin ``missing == []``. Ein Modell liest den Block
    SEINES Werkzeugs, nicht das Dokument.
    """
    doc = prompts.TOOLS_DOC
    lines = doc.split("\n")
    starts = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s{0,8}[a-z_]{3,}\(", line)
    ]
    blocks: dict[str, str] = {}
    for start, stop in zip(starts, starts[1:] + [len(lines)]):
        name = re.sub(r"\(.*", "", lines[start]).strip()
        blocks[name] = "\n".join(lines[start:stop])
    return blocks


def _entries_with_schema():
    seen = set()
    out = []
    for entry in reversed(_REGISTRY):
        name = entry.get("function", {}).get("name")
        if not name or name in seen or "response_schema" not in entry:
            continue
        seen.add(name)
        out.append((name, entry["response_schema"]))
    return list(reversed(out))


@pytest.mark.parametrize("name,schema", _entries_with_schema())
def test_every_advertised_output_field_appears_in_tools_doc(name, schema):
    blocks = _tools_doc_blocks()
    # Only tools that ARE documented in TOOLS_DOC are checked (cluster_* /
    # semantic_* helpers are documented compactly); require the tool name to be
    # present, else skip (it is reachable but not part of the prose surface).
    if name not in blocks:
        if name not in _tools_doc_text():
            pytest.skip(f"{name} not in TOOLS_DOC prose surface")
        pytest.fail(f"{name} steht in TOOLS_DOC, aber ohne eigenen Block")
    block = blocks[name]
    declared = _schema_property_names(schema)
    missing = sorted(
        key
        for key in declared
        if key not in _DOC_EXEMPT_KEYS and key not in block
    )
    assert not missing, (
        f"Der Block von {name} in TOOLS_DOC nennt die ausgelieferten "
        f"OUTPUT-Felder nicht: {missing}"
    )


def test_new_tools_are_documented_in_tools_doc():
    doc = _tools_doc_text()
    for name in ("query_count", "parallel_groups", "parallel_kwic", "document_text", "kwic_context"):
        assert name in doc, f"{name} missing from TOOLS_DOC"


def test_run_cqlf_query_doc_advertises_total_and_truncated():
    doc = _tools_doc_text()
    # The grounding-critical contract must be visible in the prose, not only the
    # schema: run_cqlf_query returns total + truncated, and a rows length is not a
    # count.
    assert "total" in doc
    assert "truncated" in doc


def test_example1_does_not_teach_count_from_kwic():
    # BEISPIEL 1 (the worked "Wie oft kommt X vor" example) must use the COUNT
    # tool, not run_cqlf_query (which returns KWIC rows, not a count).
    example = prompts.EXAMPLE_CONVERSATIONS
    assert "query_count" in example
    # It must not show run_cqlf_query as the count source in BEISPIEL 1.
    beispiel1 = example.split("BEISPIEL 2")[0]
    assert "run_cqlf_query(query=" not in beispiel1
    # The fabricated literal count tied to a KWIC call must be gone.
    assert "189 pmw" not in beispiel1


def test_method_hints_route_count_question_to_query_count():
    hints = prompts.METHOD_HINTS
    # "Wie oft kommt X vor?" -> query_count, explicitly NOT run_cqlf_query for the
    # number and NOT frequency_list (a corpus ranking).
    count_line = next(line for line in hints.splitlines() if "Wie oft kommt X vor" in line)
    assert "query_count" in count_line


def test_similar_words_doc_reflects_graceful_unavailable():
    doc = _tools_doc_text()
    # The F8 fix made similar_words return status="unavailable" instead of
    # raising; the doc must advertise that graceful degrade branch.
    assert 'status: "unavailable"' in doc
    # similar_words must NOT be described as RAISING a RuntimeError when
    # embeddings are missing (the stale claim). The corrected doc may state it
    # "DEGRADIERT NICHT mit RuntimeError" — that is fine; what is forbidden is a
    # claim that calling it leads to / produces a RuntimeError.
    similar_block = doc.split("similar_words(")[1].split("semantic_search(")[0]
    for stale in ("führt zu RuntimeError", "führt zu RuntimeError"):
        assert stale not in similar_block
    # The old SEMANTIK header that unconditionally claimed RuntimeError for the
    # whole block must be gone.
    assert "Aufruf ohne embeddings_available=true führt zu RuntimeError." not in doc
