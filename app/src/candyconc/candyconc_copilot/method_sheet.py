# -*- coding: utf-8 -*-
"""Der Methodensteckbrief: womit gemessen wurde, nicht was herauskam.

Diese Zeilen sagen einer Fachperson, ob sie eine Zahl verwenden kann:
Abfrageebene (Wortform, Lemma, CQL), Gross- und Kleinschreibung, Fenster,
Nenner mit Scope, Zeilenbilanz, Indexstand. Ohne sie steht in einer Antwort
eine Zahl ohne die Angaben, die sie einordnen.

WARUM EIGENES MODUL. Bis zum 2026-09-01 lag der Renderer in
``grounding_markdown``, zwischen den Verfassern, die den ANTWORTTEXT bauen.
Das sind zwei Anliegen: die Verfasser sagen, was gefunden wurde, dieses
Modul sagt, womit. Die Datei stand dadurch punktgenau auf ihrem
Zeilenbudget, und die naechste Reparatur an einem Verfasser schob sie
darueber.

Die Verflechtung war beim Herausloesen minimal: von allem, was der Renderer
ruft, war genau ein Name modul-lokal (``_safe_float``). Er ist mitgezogen
und wird nach ``grounding_markdown`` zurueckgereicht, wo ihn neunzehn
weitere Stellen brauchen. Es gibt keinen Zirkel: dieses Modul kennt
``grounding_markdown`` nicht.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from candyconc.answer_language import choose as _t, format_int, text_value, yes_no
from .analysis_grounding import (
    EvidenceItem,
    _normalise_example_text,
    _semantic_candidate_generation_uses_vectors,
    _semantic_row_score_kinds,
    _structured_query_diagnostic,
)
# Direktimport statt Fassade, wie in grounding_markdown: diese Helfer liegen
# in grounding_evidence und werden von analysis_grounding nicht re-exportiert.
from .grounding_evidence import (
    PROVENIENZ_JE_WERKZEUG,
    PROVENIENZ_VOREINSTELLUNG,
    dispersionsangaben,
    zaehlebene_und_nenner,
    zeilenbilanz,
)

_PROVENANCE_LABELS = {
    "query_count": "Zählung",
    "run_cqlf_query": "KWIC",
    "kwic_context": "Erweiterter KWIC-Kontext",
    "collocate_stats": "Kollokation",
    "frequency_list": "Frequenzliste",
    "ngram_frequency": "N-Gramm-Frequenz",
    "lexical_diversity": "Lexikalische Diversität",
    "metadata_values": "Metadateninventar",
    "create_docset": "Teilkorpusbildung",
    "document_search": "Dokumentsuche",
    "dispersion_offsets": "Dispersion",
    "word_sketch": "Word Sketch",
    "keyness": "Keyness",
    "semantic_search": "Semantische Suche",
}
# The same labels in an English answer (answer_language.py).
_PROVENANCE_LABELS_EN = {
    "query_count": "Count",
    "run_cqlf_query": "KWIC",
    "kwic_context": "Extended KWIC context",
    "collocate_stats": "Collocation",
    "frequency_list": "Frequency list",
    "ngram_frequency": "N-gram frequency",
    "lexical_diversity": "Lexical diversity",
    "metadata_values": "Metadata inventory",
    "create_docset": "Subcorpus",
    "document_search": "Document search",
    "dispersion_offsets": "Dispersion",
    "word_sketch": "Word sketch",
    "keyness": "Keyness",
    "semantic_search": "Semantic search",
}


def _provenance_label(tool: Any) -> str:
    labels = _t(_PROVENANCE_LABELS, _PROVENANCE_LABELS_EN)  # type: ignore[arg-type]
    return labels.get(tool, tool or _t("Werkzeug", "Tool"))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _analysis_provenance_lines(
    evidence_items: Sequence[EvidenceItem],
) -> List[str]:
    """Render compact, user-facing scope and method provenance from tool output."""

    def _number(value: Any) -> str:
        if isinstance(value, bool):
            return yes_no(value)
        if isinstance(value, int):
            return format_int(value)
        # P2.4 (Endabnahme): rohe Maschinenpraezision gehoert nicht in eine
        # Nutzeroberflaeche. 'DP 0.9557224466551584' stand seit P2.4 auf
        # JEDER Zaehlantwort, nicht nur bei ausdruecklichen
        # Verteilungsfragen. Vier Stellen sind mehr, als die Kennwerte
        # tragen, und die Zahl bleibt fuer die Zitatpruefung auffindbar,
        # weil die Evidenzoberflaeche den Rohwert weiterhin fuehrt.
        if isinstance(value, float):
            # ... nie aus einem Wert ungleich null eine Null: sonst stand
            # '12 Trefferdokumente von 250.535, Abdeckung 0' in EINER Zeile.
            gerundet = round(value, 4)
            if gerundet == 0.0 and value != 0.0:
                return f"{value:.3g}"
            return f"{gerundet:g}"
        return str(value)

    def _scope(value: Any) -> str:
        return _t({
            "corpus": "Gesamtkorpus",
            "docset": "Teilkorpus",
            "document": "Dokument",
        }, {
            "corpus": "whole corpus",
            "docset": "subcorpus",
            "document": "document",
        }).get(str(value or "").casefold(), str(value))  # type: ignore[attr-defined]

    grouping_labels = _t({
        "word": "Wortformen",
        "lemma": "Lemmata",
        "pos": "Wortarten",
    }, {
        "word": "word forms",
        "lemma": "lemmas",
        "pos": "parts of speech",
    })
    lines: List[str] = []
    docset_labels = {
        str(item.raw_surface.get("docset_id")): _normalise_example_text(
            item.raw_surface.get("label")
        )
        for item in evidence_items
        if item.tool == "create_docset"
        and item.raw_surface.get("docset_id") not in (None, "")
        and _normalise_example_text(item.raw_surface.get("label"))
    }
    for item in evidence_items:
        raw = item.raw_surface if isinstance(item.raw_surface, dict) else {}
        try:
            parsed_args = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_args = {}
        args = parsed_args if isinstance(parsed_args, dict) else {}
        method = raw.get("method") if isinstance(raw.get("method"), dict) else {}

        def _value(key: str, *sources: Dict[str, Any]) -> Any:
            for source in sources:
                if key in source and source.get(key) not in (None, "", [], {}):
                    return source.get(key)
            return None

        if str(item.status or "").strip().casefold() == "error":
            structured_diagnostic = _structured_query_diagnostic(item)
            if structured_diagnostic is not None:
                query, errors, suggestions = structured_diagnostic
                diagnostic_bits = [
                    _t("Abfrage: ", "Query: ") + _number(query),
                    _t("Parserfehler: ", "Parser errors: ") + "; ".join(errors[:3]),
                ]
                if suggestions:
                    diagnostic_bits.append(
                        _t("Korrekturvorschlag: ", "Suggested correction: ")
                        + "; ".join(suggestions[:3])
                    )
                diagnostic_bits.append(_t("keine Korpustreffer berechnet", "no corpus hits computed"))
                line = _t("Syntaxdiagnose: ", "Syntax diagnosis: ") + ", ".join(diagnostic_bits) + "."
                if line not in lines:
                    lines.append(line)
                continue
            attempted_query = _value("query", raw, args) or _value(
                "term", raw, args
            )
            error_bits = [_t("nicht als Evidenz verwendet", "not used as evidence")]
            if attempted_query not in (None, ""):
                error_bits.append(_t("Suche: ", "Search: ") + _number(attempted_query))
            message = _normalise_example_text(raw.get("message"))
            if not message:
                diagnostics = raw.get("diagnostics")
                if isinstance(diagnostics, dict):
                    errors = diagnostics.get("errors")
                    if isinstance(errors, list):
                        message = "; ".join(
                            _normalise_example_text(error)
                            for error in errors[:3]
                            if _normalise_example_text(error)
                        )
            if message:
                error_bits.append(_t("Fehler: ", "Error: ") + message)
            label = _provenance_label(item.tool)
            line = (
                label + _t(" (fehlgeschlagen): ", " (failed): ")
                + ", ".join(error_bits)
                + "."
            )
            if line not in lines:
                lines.append(line)
            continue

        bits: List[str] = []
        treffer_wert: Any = None
        scope = raw.get("scope")
        if isinstance(scope, dict):
            corpus_id = scope.get("corpus_id")
            docset_id = scope.get("docset_id")
            doc_count = scope.get("doc_count")
            if corpus_id not in (None, ""):
                bits.append(_t("Korpus ", "Corpus ") + _number(corpus_id))
            if docset_id not in (None, ""):
                bits.append(_t("Teilkorpus ", "Subcorpus ") + _number(docset_id))
            if doc_count not in (None, ""):
                bits.append(_number(doc_count) + _t(" Dokumente", " documents"))

        if item.tool == "frequency_list":
            group_by = _value("group_by", raw, args) or "word"
            bits.append(
                _t("gruppiert nach ", "grouped by ")
                + grouping_labels.get(
                    str(group_by).casefold(),
                    str(group_by),
                )
            )
            pos = _value("pos", raw, args)
            if pos not in (None, ""):
                bits.append(_t("POS-Filter ", "POS filter ") + _number(pos))
            stopwords = args.get("stopwords")
            if isinstance(stopwords, list) and stopwords:
                normalised = [
                    str(word).strip()
                    for word in stopwords
                    if str(word).strip()
                ]
                unique = list(dict.fromkeys(normalised))
                rendered = ", ".join(unique[:24])
                cardinality = (
                    _t("{} Angaben, {} verschieden", "{} entries, {} distinct").format(
                        len(normalised), len(unique))
                    if len(normalised) != len(unique)
                    else _t("{} Formen", "{} forms").format(len(unique))
                )
                bits.append(
                    _t("Stopwortfilter ({}): {}", "Stopword filter ({}): {}").format(
                        cardinality, rendered)
                )
        elif item.tool == "create_docset":
            label_value = _value("label", raw, args)
            doc_count = _value("doc_count", raw)
            token_count = _value("token_count", raw)
            if label_value not in (None, ""):
                bits.append(_t("Label „{}“", "Label “{}”").format(label_value))
            # DOKUMENT- UND TOKENZAHL STEHEN SCHON IM PROTOKOLL.
            #
            # Gemessen an zwei Live-Antworten vom 2026-09-01 machte der
            # Methodensteckbrief 53 und 62 Prozent des ausgelieferten
            # Textes aus, und vier seiner Zeilen wiederholten Zahlen, die
            # zwei Zeilen darueber schon standen ("Teilkorpus gebildet ->
            # 5.000 Dokumente, 2.328.677 Token"). Die Doppelung ist durch
            # das Experimentprotokoll entstanden, also gehoert sie dort
            # geloest, wo sie entstand.
            #
            # Was hier BLEIBT, ist die Provenienz: das Label und der
            # Filter. Sie sagen, WELCHE Menge gemeint ist und wie sie
            # zustande kam. Die Groesse ist ein Ergebnis, kein Parameter.
            # Das Protokoll nennt jetzt auch das Label, damit seine Zeile
            # allein steht und niemand hier nachschlagen muss.
            _ = (doc_count, token_count)
            filters = args.get("filters")
            if isinstance(filters, dict) and filters:
                bits.append(
                    "Filter "
                    + ", ".join(
                        f"{key}={value}" for key, value in filters.items()
                    )
                )
        elif item.tool == "metadata_values":
            # ``fields`` stand hier bis zum 2026-09-01 als tote Zuweisung,
            # uebrig geblieben, als metadatenbestand_zeilen ausgelagert
            # wurde. Es las nur und wurde nie benutzt.
            from candyconc.candyconc_copilot.grounding_inventory import metadatenbestand_zeilen
            bits.extend(metadatenbestand_zeilen(
                args, raw, _normalise_example_text, _number))
        elif item.tool in {"document_search", "semantic_search"}:
            term = _value("term", raw, args) or _value("query", raw, args)
            if term not in (None, ""):
                bits.append(_t("Suchanker „{}“", "search anchor “{}”").format(term))
            if item.tool == "semantic_search":
                level = _value("level", raw)
                if level not in (None, ""):
                    bits.append(_t("verwendete Ebene ", "level used ") + _number(level))
                semantic_meta = raw.get("meta")
                semantic_meta = (
                    semantic_meta if isinstance(semantic_meta, dict) else {}
                )
                generation = semantic_meta.get("candidateGeneration")
                generation = generation if isinstance(generation, dict) else {}
                search_mode = generation.get("searchMode")
                candidate_count = generation.get("candidateCount")
                total_vectors = generation.get("totalVectors")
                requested_top_n = generation.get("requestedTopN")
                lexical_seed_count = generation.get("lexicalSeedCount")
                if search_mode not in (None, ""):
                    bits.append(_t("Vektorsuchmodus ", "vector search mode ") + _number(search_mode))
                if candidate_count not in (None, ""):
                    candidate_scope = _number(candidate_count) + _t(
                        " geprüfte Vektorkandidaten", " checked vector candidates")
                    if total_vectors not in (None, ""):
                        candidate_scope += (
                            _t(" aus ", " out of ") + _number(total_vectors)
                            + _t(" Vektoren", " vectors")
                        )
                    bits.append(candidate_scope)
                if requested_top_n not in (None, ""):
                    bits.append(
                        _t("angefordertes Top-N ", "requested top N ") + _number(requested_top_n)
                    )
                if lexical_seed_count not in (None, ""):
                    bits.append(
                        _t("lexikalische Seeds ", "lexical seeds ") + _number(lexical_seed_count)
                    )
                rerank = semantic_meta.get("rerank")
                rerank = rerank if isinstance(rerank, dict) else {}
                if rerank.get("enabled") is True:
                    rerank_method = rerank.get("method")
                    rerank_input = rerank.get("inputCount")
                    rerank_output = rerank.get("outputCount")
                    rerank_text = _t("Reranking aktiviert", "reranking enabled")
                    if rerank_method not in (None, ""):
                        rerank_text += f" ({_number(rerank_method)})"
                    if (
                        rerank_input not in (None, "")
                        and rerank_output not in (None, "")
                    ):
                        rerank_text += (
                            f", {_number(rerank_input)} → "
                            f"{_number(rerank_output)}" + _t(" Kandidaten", " candidates")
                        )
                    bits.append(rerank_text)
                filtering = semantic_meta.get("filtering")
                filtering = filtering if isinstance(filtering, dict) else {}
                min_score = filtering.get("minScore")
                if min_score not in (None, ""):
                    bits.append(_t("Mindestscore ", "minimum score ") + _number(min_score))
                visible_scores = [
                    float(row.get("score"))
                    for row in list(raw.get("rows") or [])
                    if isinstance(row, dict)
                    and row.get("score") not in (None, "")
                    and _safe_float(row.get("score")) is not None
                ]
                score_kinds = _semantic_row_score_kinds(raw.get("rows"))
                if visible_scores:
                    score_label = (
                        score_kinds[0]
                        if len(score_kinds) == 1
                        else _t("gemischt", "mixed")
                    )
                    bits.append(
                        _t("sichtbarer Scorebereich ", "visible score range ")
                        + f"{min(visible_scores):.3f}–{max(visible_scores):.3f} "
                        f"({score_label})"
                    )
        elif item.tool == "keyness":
            target_id = str(args.get("target_docset_id") or "")
            reference_id = str(args.get("reference_docset_id") or "")
            target_label = docset_labels.get(target_id)
            reference_label = docset_labels.get(reference_id)
            if target_label and reference_label:
                bits.append(
                    _t("Richtung {} gegen {}", "direction {} against {}").format(
                        target_label, reference_label)
                )
            # P2.7: die Vergleichsgrundlage. Invariante 4 verlangt, vor der
            # Deutung eines Kontrasts die Teilkorpusgroessen zu nennen, und
            # das war aus dem Keyness-Output heraus unmoeglich.
            diagnostics = raw.get("diagnostics") if isinstance(raw, dict) else None
            # Vorbehalt aus DERSELBEN Quelle wie die Zahl: die Argumente
            # ueberleben die 512-Zeichen-Kappung von item.query nicht.
            bits.extend(zaehlebene_und_nenner(
                _value("attribute", diagnostics or {}, raw, method), None))
            pos_filter = _value("pos", diagnostics or {}, raw, method, args)
            if pos_filter not in (None, ""):
                bits.append(_t("POS-Filter ", "POS filter ") + str(pos_filter))
            if isinstance(diagnostics, dict):
                for schluessel, wort in (
                    ("target_tokens", _t("Zielkorpus", "target corpus")),
                    ("reference_tokens", _t("Referenzkorpus", "reference corpus")),
                ):
                    wert = diagnostics.get(schluessel)
                    if wert in (None, ""):
                        continue
                    dok = diagnostics.get(schluessel.replace("_tokens", "_docs"))
                    # Keyness counts word tokens only (at least one letter or
                    # digit), target_tokens is their sum. The raw size with
                    # punctuation is target_tokens_roh, the experiment log
                    # names it "Token mit Satzzeichen". English probe, run b1:
                    # "199.379 Token" there and "174.284 Tokens" here for one
                    # subcorpus, and no reader could see the difference.
                    stueck = f"{wort} {_number(wert)} " + _t(
                        "Wortformen ohne Satzzeichen", "word tokens without punctuation")
                    # Der Vorbehalt gehoert an die TOKENzahl (sie ist der
                    # statistische Nenner), nie an die DOKUMENTzahl.
                    if pos_filter not in (None, ""):
                        stueck = stueck + _t(" (nur POS {})", " (POS {} only)").format(pos_filter)
                    if dok not in (None, ""):
                        stueck = stueck + _t(" in {} Dokumenten", " in {} documents").format(_number(dok))
                    bits.append(stueck)
            min_freq = _value("min_freq", raw, method, args)
            if min_freq not in (None, ""):
                bits.append(_t("Mindestfrequenz ", "minimum frequency ") + _number(min_freq))
        elif item.tool == "collocate_stats":
            term = _value("term", args)
            window = _value("window", raw, method, args)
            min_freq = _value("min_freq", raw, method, args)
            floor_mode = _value("floor_mode", raw, method, args)
            sort_by = _value("sort_by", raw, method, args)
            within_sentence = _value(
                "within_sentence",
                raw,
                method,
                args,
            )
            if term not in (None, ""):
                bits.append(_t("Knoten „{}“", "node “{}”").format(term))
            if window not in (None, ""):
                bits.append(_t("Fenster ±", "window ±") + _number(window))
            if min_freq not in (None, ""):
                # P2.3: 'Mindestfrequenz 5' allein ist eine Fehlmeldung, denn
                # der Leser kann nicht unterscheiden, ob die Analystin den
                # Wert gewaehlt hat oder ob der adaptive Boden ihn kalibriert
                # hat. Die Herkunft steht HINTER der Zahl, damit bestehende
                # Teilstring-Anker gruen bleiben.
                from candyconc.analysis_defaults import (
                    collocate_floor_herkunft,
                )

                stueck = _t("Mindestfrequenz ", "minimum frequency ") + _number(min_freq)
                label = collocate_floor_herkunft(
                    floor_mode, _value("node_frequency", raw, method, args))
                if label:
                    stueck = f"{stueck} ({text_value(label)})"
                bits.append(stueck)
            if sort_by not in (None, ""):
                bits.append(_t("Sortierung ", "sorted by ") + _number(sort_by))
            if within_sentence not in (None, ""):
                bits.append(
                    _t("auf Satzgrenzen beschränkt: ", "limited to sentence boundaries: ")
                    + _number(within_sentence)
                )
            bits.extend(zaehlebene_und_nenner(
                _value("attribute", method, raw, args), sort_by))
        elif item.tool == "dispersion_offsets":
            term = _value("term", args)
            unit = _value("unit", raw)
            total_hits = _value("total_hits", raw)
            hit_documents = _value("nonzero_partitions", raw)
            document_count = _value("n_documents", raw)
            coverage = _value("coverage_ratio", raw)
            if term not in (None, ""):
                bits.append(_t("Suchform „{}“", "search form “{}”").format(term))
            if unit not in (None, ""):
                bits.append(_t("Einheit ", "unit ") + _number(unit))
            if total_hits not in (None, ""):
                bits.append(_number(total_hits) + _t(" Treffer", " hits"))
            if hit_documents not in (None, ""):
                document_span = _number(hit_documents) + _t(" Trefferdokumente", " documents with hits")
                if document_count not in (None, ""):
                    document_span += _t(" von ", " of ") + _number(document_count)
                bits.append(document_span)
            if coverage not in (None, ""):
                bits.append(_t("Dokumentabdeckung ", "document coverage ") + _number(coverage))
            bits.extend(
                dispersionsangaben(
                    raw, total_hits, document_count, _value, _number
                )
            )
        elif item.tool == "lexical_diversity":
            for label, key in (
                ("TTR", "ttr"),
                ("STTR", "sttr"),
                ("MATTR", "mattr"),
                ("Guiraud R", "guiraud"),
            ):
                value = _value(key, raw)
                if value not in (None, ""):
                    bits.append(f"{label} {_number(value)}")
            n_tokens = _value("n_tokens", raw)
            n_types = _value("n_types", raw)
            raw_tokens = _value("corpus_raw_token_count", raw)
            if n_tokens not in (None, ""):
                bits.append(_number(n_tokens) + _t(" analysierte Tokens", " analysed tokens"))
            if n_types not in (None, ""):
                bits.append(_number(n_types) + _t(" verschiedene Wortformen", " distinct word forms"))
            if raw_tokens not in (None, ""):
                bits.append(_number(raw_tokens) + _t(" rohe Korpustokens", " raw corpus tokens"))
            token_policy = _value("analyst_token_policy", raw)
            if token_policy == "exclude_empty_pure_punctuation_and_index_markers":
                bits.append(_t(
                    "Tokenbasis ohne Leer-, reine Satzzeichen- und Indexmarker-Tokens",
                    "token base without empty, pure punctuation and index marker tokens",
                ))
            elif _value("analyst_tokens_only", raw) is True:
                bits.append(_t("gefilterte Analysetokenbasis", "filtered analysis token base"))
            sttr_window = _value("sttr_window", raw, args)
            sttr_windows = _value("sttr_n_windows", raw)
            if sttr_window not in (None, ""):
                window_text = _t("STTR-Fenster {} Tokens", "STTR window {} tokens").format(
                    _number(sttr_window))
                if sttr_windows not in (None, ""):
                    window_text += _t(" ({} Fenster)", " ({} windows)").format(_number(sttr_windows))
                bits.append(window_text)
            mattr_window = _value("mattr_window", raw)
            if mattr_window not in (None, ""):
                bits.append(_t("MATTR-Fenster {} Tokens", "MATTR window {} tokens").format(
                    _number(mattr_window)))
        else:
            quellen = {"raw": raw, "method": method, "args": args}
            selected = [
                (label, key, *[quellen[n] for n in namen])
                for label, key, namen in PROVENIENZ_JE_WERKZEUG.get(
                    item.tool, PROVENIENZ_VOREINSTELLUNG
                )
            ]
            for label, key, *sources in selected:
                value = _value(key, *sources)
                if key == "case_insensitive" and raw.get("faltung_teilweise"):
                    # A query with %c on only some values needs a partial-folding label.
                    value = _t("teilweise ({})", "partly ({})").format(raw["faltung_teilweise"])
                if value not in (None, ""):
                    if key == "total":
                        treffer_wert = value
                    bits.append(f"{text_value(label)}: {_number(value)}")

        # P2.3: eine n-Gramm-Zahl ohne n ist nicht einzuordnen.
        _n_bits = [x for x in (_value("min_n", raw, args),
                               _value("max_n", raw, args)) if x not in (None, "")]
        if _n_bits:
            bits.append(f"n = {_number(_n_bits[0])}" if len(set(_n_bits)) == 1
                        else _t("n von {} bis {}", "n from {} to {}").format(
                            _number(_n_bits[0]), _number(_n_bits[1])))

        denominator_tokens = raw.get("denominator_tokens")
        denominator_scope = raw.get("denominator_scope")
        if denominator_tokens not in (None, ""):
            # Use word tokens as the rate denominator and show raw tokens alongside.
            from .word_denominator import ist_wortnenner

            if ist_wortnenner(raw):
                denominator = _t("Basis {} Wortformen ohne Satzzeichen",
                                 "base {} word tokens without punctuation").format(
                    _number(denominator_tokens))
                roh = raw.get("denominator_tokens_raw")
                if roh not in (None, ""):
                    denominator += _t(" (von {} Token)", " (of {} tokens)").format(_number(roh))
            else:
                denominator = _t("Basis {} Tokens", "base {} tokens").format(_number(denominator_tokens))
            if denominator_scope not in (None, ""):
                denominator += _t(" im ", " in the ") + _scope(denominator_scope)
            bits.append(denominator)
        rows_returned = raw.get("rows_seen")
        if item.tool == "collocate_stats":
            rows_returned = raw.get("result_count") or rows_returned
        if rows_returned in (None, "") and isinstance(raw.get("rows"), list):
            rows_returned = len(raw["rows"])
        if rows_returned not in (None, ""):
            bits.append(zeilenbilanz(treffer_wert, rows_returned, _number))
        stichprobe = raw.get("sample")
        if item.tool == "run_cqlf_query" and isinstance(stichprobe, dict) and stichprobe.get("drawn"):
            # Label sampled rows with their seed, including the default sample drawn
            # when no explicit sample size is requested.
            bits.append(
                _t("Zufallsstichprobe von {} aus {} Treffern, Seed {}",
                   "random sample of {} from {} hits, seed {}").format(
                    _number(stichprobe.get("drawn")), _number(stichprobe.get("population")),
                    stichprobe.get("seed"))
                + (_t(", nur über einen gedeckelten Scan", ", only over a capped scan")
                   if stichprobe.get("population_partial") else "")
            )
        elif bool(raw.get("truncated")) and item.tool == "trend_analysis":
            # trend_analysis thins a long series evenly and keeps both ends
            # (analysis_defaults.perioden_ausduennen), it is no top N.
            geliefert = raw.get("grounding_periods_total")
            if geliefert in (None, "") and isinstance(raw.get("periods"), list):
                geliefert = len(raw["periods"])
            gesamt = raw.get("periods_total")
            bits.append(
                f"Reihe gleichmäßig ausgedünnt auf {_number(geliefert)} von {_number(gesamt)} Perioden"
                if geliefert not in (None, "") and gesamt not in (None, "")
                else "gleichmäßig ausgedünnte Reihe"
            )
        elif bool(raw.get("truncated")):
            bits.append(
                _t("begrenzter KWIC-Ausschnitt", "limited KWIC excerpt")
                if item.tool in {"run_cqlf_query", "kwic_context"}
                else _t("Top-N-Ausschnitt", "top N excerpt")
            )
        if not bits:
            continue
        label = _provenance_label(item.tool)
        if item.tool == "semantic_search":
            score_kinds = _semantic_row_score_kinds(raw.get("rows"))
            if (
                score_kinds == ["lexical"]
                and _semantic_candidate_generation_uses_vectors(raw)
            ):
                label = _t("Hybride semantische Suche", "Hybrid semantic search")
            elif score_kinds == ["lexical"]:
                label = _t("Lexikalischer Such-Fallback", "Lexical search fallback")
            elif "lexical" in score_kinds:
                label = _t("Semantische Suche mit lexikalischen Kandidaten",
                           "Semantic search with lexical candidates")
        line = f"{label}: " + ", ".join(str(bit) for bit in bits) + "."
        if line not in lines:
            lines.append(line)
    return lines
