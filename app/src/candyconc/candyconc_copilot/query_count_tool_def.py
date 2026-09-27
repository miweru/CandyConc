# -*- coding: utf-8 -*-
"""Schema des Werkzeugs query_count, ausgelagert aus tool_wrappers.

Die Aufschlüsselung nach einem Metadatenfeld (``nach``, ``filters``) steht in
``aufschluesselung``.
"""

from __future__ import annotations

from typing import Any, Dict

QUERY_COUNT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_count",
        "description": (
            "Return ONLY the exact total hit count for a plain-text or CQLF query "
            "(no KWIC rows). USE THIS for 'Wie oft kommt X vor?' / frequency-of-a-"
            "term questions — run_cqlf_query returns KWIC rows, NOT a count, and "
            "frequency_list is a whole-corpus ranking, not a single term count. "
            "Optional corpus/docset scoping and case folding. per_million is "
            "normalised by denominator_tokens: the whole corpus for an unscoped "
            "query, or the selected docset's token count for a scoped query. "
            "denominator_scope and denominator_source record that provenance; "
            "corpus_tokens always reports the full corpus size. "
            "nach=<Metadatenfeld> (z. B. register, prompting_method) liefert in EINEM "
            "Aufruf rows mit total, docs, tokens und per_million je Wert, dazu Gries' DP "
            "über die Werte als Partition (dp_nach, dp_norm_nach), statt je Wert "
            "ein Teilkorpus anzulegen. filters schränkt vorher ein wie bei create_docset, "
            "z. B. {\"register\": \"spoken\", \"text_type\": \"ai\"}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Plain text or CQLF query string"},
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID ODER Subkorpus-Name (optional).",
                },
                "filters": {
                    "type": "object",
                    "description": "Metadatenfilter wie bei create_docset (optional).",
                },
                "nach": {
                    "type": "string",
                    "description": "Metadatenfeld, nach dessen Werten aufgeschlüsselt wird (optional, höchstens 50 Werte).",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Gross-/Kleinschreibung ignorieren (Default true), nur fuer die einfache Wortsuche. In CQL faltet allein %c: [word=\"und\" %c] faltet, [word=\"und\"] nicht.",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "corpus": {"type": "string"},
            "docset_id": {"type": "string"},
            "case_insensitive": {"type": "boolean"},
            "filters": {"type": "object"},
            "nach": {"type": "string"},
        },
        "required": ["query"],
    },
}
