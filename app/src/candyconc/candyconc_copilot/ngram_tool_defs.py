"""Die Werkzeugdefinitionen der n-Gramm-Flaeche, als reine Daten.

Ausgelagert wie ``keyness_tool_def``: ``tool_wrappers`` stand an seinem
LOC-Budget von 6000, und Budgets duerfen hier fallen, nie steigen. Diese
beiden Woerterbuecher haengen an nichts ausser der Typangabe, sie sind
deshalb der billigste Schnitt. Die Antwortschemata bleiben drueben, weil
sie die ``_obj``/``_int``-Helfer brauchen.
"""

from __future__ import annotations

from typing import Any, Dict


NGRAM_FREQUENCY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ngram_frequency",
        "description": (
            "Most frequent contiguous word n-grams (phrases) over the corpus or a "
            "docset. min_n/max_n bound the n-gram length (e.g. min_n=2, max_n=3 for "
            "bi- and trigrams). Top 100 rows; total candidate count in 'total'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "min_n": {"type": "integer", "description": "Kleinste n-Gramm-Länge.", "default": 2},
                "max_n": {"type": "integer", "description": "Größte n-Gramm-Länge.", "default": 2},
                "docset_id": {
                    "type": "string",
                    "description": "Docset-ID ODER Subkorpus-Name (optional, sonst ganzes Korpus).",
                },
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
                "limit": {"type": "integer", "description": "Max. zurückgegebene Zeilen (<=100).", "default": 100},
            },
            "required": [],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "min_n": {"type": "integer"},
            "max_n": {"type": "integer"},
            "docset_id": {"type": "string"},
            "corpus": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": [],
    },
}


NGRAM_CONTRAST_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ngram_contrast",
        "description": (
            "Contrast word n-gram rates between TWO docsets (or subcorpus "
            "names): which phrases are relatively more frequent in the target "
            "vs the reference side. Rates are per million n-gram positions of "
            "the same order n, the denominators per side are in 'populations'. "
            "Rows are ranked by the ABSOLUTE diff_per_million, so both "
            "directions appear: > 0 more frequent in the target, < 0 in the "
            "reference. Word forms are case-sensitive: 'Viele Menschen' and "
            "'viele Menschen' are separate rows, unlike a %c CQL count. "
            "Build the two sides with create_docset or resolve_subcorpus first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_docset_id": {"type": "string", "description": "Docset-ID ODER Subkorpus-Name (Seite A)."},
                "reference_docset_id": {"type": "string", "description": "Docset-ID ODER Subkorpus-Name (Seite B)."},
                "min_n": {"type": "integer", "default": 2},
                "max_n": {"type": "integer", "default": 2},
                "corpus": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["target_docset_id", "reference_docset_id"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "target_docset_id": {"type": "string"},
            "reference_docset_id": {"type": "string"},
            "min_n": {"type": "integer"},
            "max_n": {"type": "integer"},
            "corpus": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["target_docset_id", "reference_docset_id"],
    },
}
