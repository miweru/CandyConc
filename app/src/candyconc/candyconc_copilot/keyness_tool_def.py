# -*- coding: utf-8 -*-
"""Aufrufvertrag des keyness-Werkzeugs (Funktions- und Argumentschema).

Ausgelagert, weil ``tool_wrappers`` eine Fassade ist und keine Ablage fuer
Datenstrukturen. Die Beschreibungen hier gehen als Funktionsschema an das
Modell und zahlen NICHT auf ``STATIC_CORE_CHAR_COUNT`` ein, anders als die
Prosa in ``prompts.TOOLS_DOC``. Deshalb steht die ausfuehrliche Anleitung zu
``sort_by`` und ``target_context_query`` hier und nicht dort.
"""

from __future__ import annotations

from typing import Any, Dict

from candyconc.services.tools.keyness import DEFAULT_MIN_FREQ as _DEFAULT_MIN_FREQ
from .schema_parts import _bool, _int, _num, _obj, _rows_response, _str

KEYNESS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "keyness",
        "description": (
            "Compute directed keyness for target vs reference. To compare two "
            "named corpora, pass `target_corpus` and `reference_corpus` using "
            "exact corpus names supplied by the user or runtime context; never "
            "guess corpus names. This is the supported path for whole-corpus "
            "comparisons. Use "
            "`target_docset_id`/`reference_docset_id` only for saved subcorpora, "
            "and `target`/`reference` only for two TOKEN STREAMS the caller already holds (they are counted, so a list of candidate words is not a valid target: count each candidate with query_count per side instead). "
            "`chi2_cell` is a chi-square cell contribution; mention direction in visible answers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                # LIVE am 2026-09-02: das Modell uebergab sieben zu
                # pruefende Kandidatenformen als ``target`` und eine
                # ``reference_docset_id``. Die naheliegende Lesart von
                # "Target tokens" war "die Woerter, um die es geht". Der
                # Zaehler dahinter bildet aber einen Counter ueber den
                # Strom (services/tools/keyness.py:435-438), sieben Kandidaten
                # waeren also sieben Tokens Gesamtmasse.
                "target": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Zielseite als TOKENSTROM, aus dem die Frequenzen "
                        "gezählt werden, KEINE Kandidatenliste. Wer eine "
                        "Wortliste gegen ein Teilkorpus prüfen will, "
                        "zählt je Kandidat mit query_count auf beiden "
                        "Seiten und normiert auf die Tokenzahl der Seite."
                    ),
                },
                "reference": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Referenzseite als TOKENSTROM, gezählt wie "
                        "``target``, keine Kandidatenliste."
                    ),
                },
                "target_corpus": {
                    "type": "string",
                    "description": "Exakter, bereits belegter Name des Zielkorpus für einen Korpus-vs-Korpus-Vergleich.",
                },
                "reference_corpus": {
                    "type": "string",
                    "description": "Exakter, bereits belegter Name des Referenzkorpus für einen Korpus-vs-Korpus-Vergleich.",
                },
                "target_docset_id": {
                    "type": "string",
                    "description": "Docset-ID ODER gespeicherter Subkorpus-Name für Zielkorpus (optional).",
                },
                "reference_docset_id": {
                    "type": "string",
                    "description": "Docset-ID ODER gespeicherter Subkorpus-Name für Referenzkorpus (optional).",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "pos_map": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Optional token to POS mapping",
                },
                "pos": {
                    "type": "string",
                    "description": "POS-Präfixfilter für Docsets oder Wortlisten, nicht für Korpus-vs-Korpus.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Wie viele Zeilen zurückkommen sollen, nach sort_by "
                        "absteigend. Ohne Angabe die ganze Tabelle. WÄHLE "
                        "EINE ZAHL, die du lesen kannst: eine vollständige "
                        "Tabelle wird für den nächsten Schritt auf eine "
                        "kleine Auswahl verdichtet, eine angeforderte Zahl "
                        "kommt ganz bei dir an. rows_total nennt dir immer, "
                        "wie lang die Tabelle wirklich war."
                    ),
                },
                "min_freq": {
                    "type": "integer",
                    "description": (
                        "Minimale kombinierte Ziel+Referenz-Frequenz, ab der ein "
                        "Kandidat in die Keyness-Statistik eingeht (Default 5, der "
                        "Reliabilitäts-Floor; identisch zur REST-Route)."
                    ),
                    "default": _DEFAULT_MIN_FREQ,
                },
                # Die Beschreibung steht HIER und nicht in TOOLS_DOC: das
                # Funktionsschema geht ohnehin an das Modell und zahlt nicht
                # auf STATIC_CORE_CHAR_COUNT ein.
                "sort_by": {
                    "type": "string",
                    "description": (
                        "Spalte, nach der absteigend sortiert wird, BEVOR die "
                        "Zeilen gekappt werden. Default ll_signed. 'lrc' ist "
                        "das konservative Log Ratio: es raeumt "
                        "Nulldivisions-Ausreisser (Referenzfrequenz 0) von der "
                        "Spitze und ist die Rangfolge, die replizierte "
                        "Keyness-Studien meist meinen. Weiter erlaubt: ll, "
                        "chi2, chi2_signed, chi2_cell, chi2_cell_signed, "
                        "log_ratio, bic, diff_per_million, target_freq, "
                        "reference_freq, target_per_million, "
                        "reference_per_million, expected_min, p_value, "
                        "q_value. Ein unbekannter Wert ist ein Fehler, kein "
                        "stiller Ersatz."
                    ),
                    "default": "ll_signed",
                },
                "target_context_query": {
                    "type": "string",
                    "description": (
                        "Ziel ist das KONTEXTFENSTER dieser Abfrage, Referenz "
                        "das Korpus OHNE dieses Fenster (Konfiguration "
                        "publizierter Kollokationsstudien). Anders als "
                        "collocate_stats: dort gilt der Paar-Ereignisraum, "
                        "hier zählt jede Position genau einmal, damit "
                        "log_ratio und lrc definiert sind. Schliesst "
                        "target/reference und Docsets aus."
                    ),
                },
                "context_window": {
                    "type": "integer", "minimum": 1, "default": 5,
                    "description": "Fensterbreite je Seite fuer target_context_query.",
                },
                "attribute": {
                    "type": "string", "enum": ["word", "lemma"], "default": "word",
                    "description": (
                        "Zählebene der Kandidaten: Wortformen oder Lemmata. "
                        "Publizierte Studien zählen meist Lemmata. Gilt für "
                        "target_context_query, Docset-Kontraste und "
                        "Korpus-Kontraste. NICHT fuer target/reference: diese "
                        "Listen kommen vom Aufrufer, das Korpus wird dafür "
                        "nicht gezählt. Welche Ebene gezählt wurde, steht in "
                        "diagnostics.attribute."
                    ),
                },
            },
            "required": [],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "target": {"type": "array", "items": {"type": "string"}},
            "reference": {"type": "array", "items": {"type": "string"}},
            "target_corpus": {"type": "string"},
            "reference_corpus": {"type": "string"},
            "target_docset_id": {"type": "string"},
            "reference_docset_id": {"type": "string"},
            "corpus": {"type": "string"},
            "pos_map": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "pos": {"type": "string"},
            "min_freq": {"type": "integer"},
            "sort_by": {"type": "string"},
            "target_context_query": {"type": "string"},
            "context_window": {"type": "integer"},
            "attribute": {"type": "string"},
        },
        "required": [],
    },
}


KEYNESS_RESPONSE = _rows_response(
    {
        "word": _str(),
        "target_freq": _int(),
        "reference_freq": _int(),
        "target_per_million": _num(),
        "reference_per_million": _num(),
        "diff_per_million": _num(),
        "direction": _str(),
        "chi2": _num(),
        "chi2_signed": _num(),
        "chi2_cell": _num(),
        "chi2_cell_signed": _num(),
        "ll": _num(),
        "ll_signed": _num(),
        "log_ratio": _num(),
        "log_ratio_ci_low": _num(),
        "log_ratio_ci_high": _num(),
        # P2.5: konservatives Log Ratio (Hardie 2014, Evert). Die nullnaehere
        # Grenze des Intervalls, 0 sobald es die Null enthaelt, Bonferroni ueber
        # den vollen Kandidatensatz bei alpha=0.001. Gehoert HIER hin und nicht
        # an collocate_stats: es ist auf der Token-Tabelle definiert, die
        # keyness ohnehin rechnet.
        "lrc": _num(),
        "bic": _num(),
        "p_value": _num(),
        "q_value": _num(),
        # Reliability gating (FT-KEYNESS-RESEARCH): expected_min is the smallest
        # expected cell count; low_reliability flags candidates below the min-cell
        # threshold (E_min<5) whose stats are unreliable.
        "expected_min": _num(),
        "low_reliability": _bool(),
        # Welche Schreibung welchen Anteil traegt, je Seite. Fehlt der
        # Schluessel, traegt das Etikett die Zahl allein (tests/ai/test_faltung).
        "surface_variants": {"type": ["object", "null"], "additionalProperties": {
            "type": "object", "additionalProperties": {"type": ["integer", "null"]}}},
    },
    extra_top={
        # Selbstbestimmtes Ende (2026-09-17): der limit-Parameter macht die
        # Auswahl sichtbar -- rows_total die Wahrheit ueber die Tabelle,
        # rows_returned die gelieferte Zahl, sortiert_nach das Kriterium.
        # Ohne Deklaration wuerde additionalProperties=False sie abweisen
        # (MCP-Route: HTTP 500).
        "rows_total": _int(),
        "rows_returned": _int(),
        "sortiert_nach": _str(),
        # P2.7: Vergleichsgrundlage. _obj setzt
        # additionalProperties=False, ohne Deklaration wuerde die
        # eigene Validierung das Feld abweisen.
        "diagnostics": _obj(
            {
                # target_tokens is the population after the analysis-token filter.
                # The numerator and denominator must use the same filtered population.
                "target_tokens": _int(),
                "reference_tokens": _int(),
                # Und daneben die volle Teilkorpusgroesse, damit die
                # gerechnete Zahl keine verschwiegene ist. Ohne diese
                # Deklaration wuerde additionalProperties=False sie
                # abweisen, und das Werkzeug antwortete mit 500.
                "target_tokens_roh": _int(),
                "reference_tokens_roh": _int(),
                "target_docs": _int(),
                "reference_docs": _int(),
                # "docset" oder "rest_des_korpus". 1317 Dokumente sehen gleich
                # aus, ob sie ein zweites Docset sind oder der Rest des Korpus,
                # und die Deutung des Kontrasts unterscheidet sich.
                "reference_kind": _str(),
                # Kontext-Keyness (P2.5): gehoeren zur Zahl, nicht in den Aufruf.
                "node_hits": _int(),
                "context_window": _int(),
                "attribute": _str(),
                # Positionen im Fenster und davon jene ohne Lexikonwert. Der
                # Nenner target_tokens ist die Differenz, sonst waere a/n1
                # systematisch zu klein.
                "context_positions": _int(),
                "unlabelled_positions": _int(),
                # Der Vorbehalt gehoert in DIESELBE Quelle wie die Zahl.
                # Vorher kam er aus den Aufrufargumenten, und die parst der
                # Renderer aus item.query, das bei ueber 512 Zeichen
                # abgeschnitten und damit kein gueltiges JSON mehr ist.
                # Dann verschwand der Vorbehalt, WAEHREND die Zahl
                # POS-gefiltert blieb: dieselbe Fehlinformation wie zuvor,
                # nur in der anderen Richtung. Nur das Werkzeug weiss,
                # welches pos es tatsaechlich angewandt hat.
                "pos": _str(),
                # Eine Zeile steht fuer alle Gross- und Kleinschreibungen.
                "case_policy": _str(),
            },
            required=[],
        ),
    },
)
