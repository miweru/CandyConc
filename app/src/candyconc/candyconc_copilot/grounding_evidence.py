"""Grounding evidence surface: raw tool-output reduction to quotable lines.

K3 Slice 1: byte-verbatim extraction from ``analysis_grounding.py`` (the
facade). Layer 1 of the grounding decomposition: imports only
``grounding_schemas``.

Moved here: the contiguous surface block ``_semantic_row_score_kinds`` ..
``build_grounding_surface``, result-scope classification
(``result_scope_from_output``, ``output_is_truncated`` / ``_partial`` /
``_sampled``), row/cluster/metric sampling and quoting helpers, and the two
entry points ``extract_raw_surface`` and ``build_grounding_surface``.

``analysis_grounding`` re-exports every name below, so all existing imports
and ``analysis_grounding.<name>`` monkeypatch seams keep working. This module
must never import ``analysis_grounding`` or ``grounding_contracts``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Sequence

from candyconc.i18n import lt
from candyconc.utils.text_normalize import normalize_index_display_text

from candyconc.answer_language import choose as _t

from .grounding_field_contract import (
    felder_der_modellsicht as _felder_der_modellsicht,
)
from .grounding_schemas import (
    DEFAULT_GROUNDING_ROW_LIMIT,
    KWIC_GROUNDING_QUOTE_LIMIT,
    _compact_text,
)

#: Felder, die in der UNBESCHRAENKTEN Belegaufzeichnung ihre Struktur behalten.
#: Alles andere wird dort zu Text verdichtet, und das ist fuer Darstellung
#: richtig. Eine deterministische Wache liest die Aufzeichnung aber
#: MASCHINELL. ``surface_variants`` als 120-Zeichen-Text bedeutet: die Wache
#: sieht ein Feld, kann es nicht auswerten und schweigt. Genau so waren am
#: 2026-08-30 zwei Wachen auf dem Produktivweg abgeschaltet, obwohl beide
#: Testreihen gruen standen.
STRUKTUR_ERHALTEN = frozenset({"surface_variants"})


def _semantic_row_score_kinds(rows: Any) -> List[str]:
    """Return the explicit score provenance carried by visible search rows."""

    kinds: List[str] = []
    for row in _sample_items(rows):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("score_kind") or "").strip().lower()
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def _semantic_rows_include_embedding_scores(rows: Any) -> bool:
    return any(
        kind in {"cosine", "embedding", "semantic", "vector"}
        for kind in _semantic_row_score_kinds(rows)
    )


def _semantic_candidate_generation_uses_vectors(output: Any) -> bool:
    """Recognise vector retrieval even when the visible reranker is lexical."""

    if not isinstance(output, dict):
        return False
    meta = output.get("meta")
    if not isinstance(meta, dict):
        return False
    generation = meta.get("candidateGeneration")
    if not isinstance(generation, dict):
        return False
    method = str(generation.get("method") or "").strip().casefold()
    index_type = str(generation.get("indexType") or "").strip().casefold()
    return bool(
        re.search(r"(?:faiss|vector|embedding|ann|hnsw)", method)
        or re.search(r"(?:faiss|indexflat|hnsw|ivf|pq)", index_type)
    )


def result_scope_from_output(output: Any) -> Dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    scope: Dict[str, Any] = {}
    rows_seen = _count_or_sample_len(output.get("rows"))
    if rows_seen is not None:
        scope["rows_seen"] = rows_seen
    score_kinds = _semantic_row_score_kinds(output.get("rows"))
    if score_kinds:
        scope["score_kinds"] = score_kinds
    if isinstance(output.get("offsets"), list):
        scope["offsets_seen"] = len(output.get("offsets", []))
    if isinstance(output.get("tables"), dict):
        scope["table_names"] = list(output.get("tables", {}).keys())[:6]
    clusters_seen = _count_or_sample_len(output.get("clusters"))
    if clusters_seen is not None:
        scope["clusters_seen"] = clusters_seen
    meta = output.get("meta")
    if isinstance(meta, dict):
        exactness = meta.get("exactness")
        candidate_generation = meta.get("candidateGeneration")
        if exactness not in (None, ""):
            scope["exactness"] = exactness
        if isinstance(candidate_generation, dict):
            search_mode = candidate_generation.get("searchMode")
            if search_mode not in (None, ""):
                scope["searchMode"] = search_mode
    if output.get("total") not in (None, ""):
        scope["total"] = output.get("total")
    if output.get("status") not in (None, ""):
        scope["status"] = output.get("status")
    for flag in ("truncated", "partial"):
        if bool(output.get(flag)):
            scope[flag] = True
    if output_is_sampled(output):
        scope["sampled"] = True
        sample = output.get("sample")
        if isinstance(sample, dict):
            scope["sample"] = {
                key: sample[key]
                for key in (
                    "requested",
                    "drawn",
                    "seed",
                    "population",
                    "population_partial",
                    "method",
                )
                if sample.get(key) not in (None, "")
            }
    return scope


def output_is_truncated(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    for key in ("truncated", "has_more", "more"):
        if bool(output.get(key)):
            return True
    return False


def output_is_partial(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    return bool(output.get("partial"))


def output_is_sampled(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    if bool(output.get("sampled")):
        return True
    sample = output.get("sample")
    return bool(
        isinstance(sample, dict)
        and any(
            sample.get(key) not in (None, "")
            for key in ("requested", "drawn", "seed", "population", "method")
        )
    )


def _count_or_sample_len(value: Any) -> Any:
    if isinstance(value, list):
        return len(value)
    if not isinstance(value, dict):
        return None
    if value.get("count") not in (None, ""):
        return value.get("count")
    sample = value.get("sample")
    if isinstance(sample, list):
        return len(sample)
    return None


def _sample_items(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, dict):
        return []
    sample = value.get("sample")
    if isinstance(sample, list):
        items: List[Any] = []
        for entry in sample:
            if isinstance(entry, dict) and set(entry.keys()).issubset({"count", "sample"}):
                items.append(entry.get("sample"))
            else:
                items.append(entry)
        return items
    if isinstance(sample, dict):
        return [sample]
    return []


# Emergency row boundary for the model view and evidence surface.
# Respect requested and returned row counts within this boundary so the
# interpretation can use the results the model requested.
SICHT_ZEILEN_REISSLEINE = 200


def _grounding_row_indices(
    rows: Sequence[Any],
    *,
    limit: int,
    gleichmaessig: bool = False,
    sortiert_nach: str | None = None,
) -> tuple[List[int], str]:
    """Select displayed rows by their indices in the tool result.

    Directed rankings retain both sides. For position-sorted concordance
    lists and samples, select evenly across the result so a prefix does not
    favor early corpus sections. Samples already in draw order keep that order.
    """

    if len(rows) <= limit:
        return list(range(len(rows))), ""

    def _kopf() -> tuple[List[int], str]:
        if gleichmaessig:
            from candyconc.analysis_defaults import gleichmaessige_auswahl
            from candyconc.candyconc_copilot.view_row_selection import auswahlangabe

            return gleichmaessige_auswahl(len(rows), limit), auswahlangabe(len(rows))
        return list(range(limit)), ""

    groups: Dict[str, List[int]] = {}
    for nummer, row in enumerate(rows):
        if not isinstance(row, dict):
            return _kopf()
        direction = str(row.get("direction") or "").strip().casefold()
        if not direction:
            return _kopf()
        groups.setdefault(direction, []).append(nummer)
    if len(groups) < 2:
        return _kopf()

    # Use the measure that sorted the tool result. Compare magnitudes in
    # each direction so strong reference-side rows remain visible when a
    # signed descending table places them at the end.
    kriterium = str(sortiert_nach or "").strip()
    if kriterium and not any(kriterium in rows[nummer] for nummer in range(len(rows))):
        kriterium = ""

    def score(nummer: int) -> float:
        row = rows[nummer]
        if kriterium:
            try:
                return abs(float(row.get(kriterium)))
            except (TypeError, ValueError):
                return -1.0
        for key in (
            "ll_signed",
            "ll",
            "chi2_signed",
            "chi2",
            "diff_per_million",
            "log_ratio",
        ):
            try:
                return abs(float(row.get(key)))
            except (TypeError, ValueError):
                continue
        return 0.0

    selected: List[int] = []
    group_count = len(groups)
    base, remainder = divmod(limit, group_count)
    for index, group_rows in enumerate(groups.values()):
        quota = base + int(index < remainder)
        selected.extend(sorted(group_rows, key=score, reverse=True)[:quota])
    if kriterium:
        return selected[:limit], (
            f"balanced_by_direction, je Richtung die Zeilen mit dem größten |{kriterium}|"
        )
    return selected[:limit], "balanced_by_direction"


def _grounding_row_sample(
    rows: Sequence[Any],
    *,
    limit: int,
    gleichmaessig: bool = False,
) -> tuple[List[Any], str]:
    """Die Zeilen zu ``_grounding_row_indices``, ohne ihre Indizes."""
    nummern, auswahl = _grounding_row_indices(rows, limit=limit, gleichmaessig=gleichmaessig)
    return [rows[i] for i in nummern], auswahl


def _surface_row_dict(
    row: Any,
    *,
    limit_keys: int | None = 8,
    required_keys: Sequence[str] = (),
    werkzeug: str | None = None,
) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {"value": _compact_text(row, 120)}
    required = [
        actual
        for requested in required_keys
        for actual in row
        if str(actual).casefold() == str(requested).casefold()
    ]
    # Hat das Werkzeug einen Feldvertrag, IST er die Auswahl: kein Schnitt
    # bei acht und kein alphabetischer Rest. Die gemeinsame Vorzugsliste
    # unten liess dem Modell bei keyness weder eine Effektstaerke noch eine
    # der beiden Raten und bei collocate_stats vier Masse derselben Familie
    # statt der Randsumme f2. Siehe grounding_field_contract.
    #
    # NUR fuer die beschraenkte Sicht. ``limit_keys=None`` ist die
    # UNBESCHRAENKTE Belegaufzeichnung (fact_surface), gegen die spaeter
    # geprueft wird. Sie muss vollstaendig bleiben, sonst kuerzt der
    # Vertrag die Beweislage statt der Darstellung: eine Zahl, die das
    # Modell nicht zitieren soll, muss trotzdem nachweisbar bleiben.
    vertragsfelder = (
        _felder_der_modellsicht(werkzeug, row, pflicht=required_keys)
        if limit_keys is not None
        else None
    )
    if vertragsfelder is not None:
        return {
            key: (
                _compact_text(row.get(key), 120)
                if isinstance(row.get(key), (dict, list))
                else row.get(key)
            )
            for key in vertragsfelder
        }
    preferred = [
        "rank",
        "word",
        "kw",
        "label",
        "doc_id",
        *required,
        "direction",
        "target_freq",
        "reference_freq",
        "diff_per_million",
        "ll_signed",
        "q_value",
        "low_reliability",
        "f",
        "f2",
        "frequency",
        "score_key",
        "score_kind",
        "score",
        "logdice",
        "mi3",
        "mi",
        "t",
        "ll",
        "dice",
        "chi2_cell",
        "delta_p_nc",
        "delta_p_cn",
        "lmi",
        "npmi",
        "z",
        "left",
        "right",
        "snippet",
        "file",
    ]
    ordered = list(
        dict.fromkeys(key for key in preferred if key in row)
    )
    ordered.extend(sorted(key for key in row.keys() if key not in ordered))
    surface: Dict[str, Any] = {}
    selected = ordered if limit_keys is None else ordered[:limit_keys]
    for key in selected:
        value = row.get(key)
        if isinstance(value, (dict, list)):
            if limit_keys is None and key in STRUKTUR_ERHALTEN:
                surface[key] = value
            else:
                surface[key] = _compact_text(value, 120)
        else:
            surface[key] = value
    return surface


def _surface_semantic_meta(meta: Any) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    surface: Dict[str, Any] = {}
    if meta.get("exactness") not in (None, ""):
        surface["exactness"] = meta.get("exactness")
    for section_name, allowed_keys in (
        (
            "candidateGeneration",
            (
                "backend",
                "level",
                "method",
                "indexType",
                "searchMode",
                "requestedTopN",
                "requestedContext",
                "candidateLimit",
                "candidateCount",
                "totalVectors",
                "lexicalSeedCount",
                "oversample",
            ),
        ),
        ("rerank", ("enabled", "method", "inputCount", "outputCount")),
        ("filtering", ("docsetApplied", "docsetDocCount", "minScore", "postFilterCandidateCount")),
    ):
        section = meta.get(section_name)
        if not isinstance(section, dict):
            continue
        compact_section = {
            key: section.get(key)
            for key in allowed_keys
            if section.get(key) not in (None, "", [], {})
        }
        if compact_section:
            surface[section_name] = compact_section
    return surface


def _surface_cluster_dict(cluster: Any, *, limit_keys: int = 6) -> Dict[str, Any]:
    surface = _surface_row_dict(cluster, limit_keys=limit_keys)
    if isinstance(cluster, dict):
        samples = cluster.get("samples")
        if isinstance(samples, dict):
            samples = samples.get("sample")
        if isinstance(samples, list):
            cleaned = [
                _normalise_example_text(sample)
                for sample in samples[:8]
                if _normalise_example_text(sample)
            ]
            if cleaned:
                surface["samples"] = cleaned
    return surface


def _normalise_example_text(value: Any) -> str:
    # Strip the index-only '|LBR|' linebreak sentinel via the SAME helper KWIC
    # display uses (normalize_index_display_text), so grounded examples never
    # leak the raw marker. Grounded snippets render inline (markdown backticks),
    # so the resulting newlines collapse to single spaces here.
    return " ".join(normalize_index_display_text(value or "").split()).strip()


def _simple_analysis_input_quote(query: Any) -> str:
    """Expose a plain analysis term without leaking numeric tool settings."""

    payload = query
    if isinstance(query, str):
        try:
            payload = json.loads(query)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {"query": query}
    if not isinstance(payload, dict):
        return ""
    for key in ("term", "query"):
        value = _normalise_example_text(payload.get(key))
        simple_cql_match = re.fullmatch(
            r'\[\s*(?:word|lemma|pos|tag)\s*=\s*"([^"\\]+)"\s*\]',
            value,
            re.IGNORECASE,
        )
        if simple_cql_match is not None:
            value = _normalise_example_text(simple_cql_match.group(1))
        if (
            value
            and len(value) <= 80
            and any(char.isalpha() for char in value)
            and all(
                char.isalpha() or char.isspace() or char in {"-", "_", "'", "’"}
                for char in value
            )
        ):
            return _compact_text(f"analysis_input={value}", 120)
    return ""


def _kwic_line(left: str, kw: str, right: str, row: Any) -> str:
    """Left, node and right as one line.

    A row of an index with the original spacing says whether a space stands
    before and after the node (``ws_before_kw``, ``ws_after_kw``), so the line
    reads as written ("the freedom-loving people"). Without the flags every
    part is separated by one space, as before.
    """
    flags = row if isinstance(row, dict) else {}
    vorher, nachher = flags.get("ws_before_kw"), flags.get("ws_after_kw")
    if not (isinstance(vorher, bool) and isinstance(nachher, bool)) or not kw:
        return " ".join(part for part in (left, kw, right) if part).strip()
    return (
        left + (" " if left and vorher else "") + kw + (" " if right and nachher else "") + right
    ).strip()


def _row_quote(prefix: str, index: int, row: Dict[str, Any]) -> str:
    """Zeilenbeschriftung der Evidenzoberflaeche.

    ``prefix`` und ``index`` bilden zusammen den ECHTEN Referenzpfad
    (H11.8). Bis dahin war die Beschriftung dreifach irrefuehrend: sie
    zaehlte ab 1, waehrend der Resolver ab 0 indexiert, sie schrieb den
    Container im Singular (``row`` statt ``rows``), und bei Tabellen setzte
    sie Klammern, wo der Resolver einen Punkt braucht. Ein Modell, das die
    Anzeige abschrieb, machte drei Fehler auf einmal, und der schlimmste
    davon lieferte keinen Platzhalter, sondern die NACHBARZEILE. Eine
    falsche Zahl mit richtigem Aussehen faengt keine Zahlenachse, denn der
    Wert steht in der Evidenz.
    """
    return _compact_text(f"{prefix}[{index}] {row}", 220)


def _kwic_quote(index: int, row: Dict[str, Any]) -> str:
    left = _normalise_example_text(row.get("left"))
    kw = _normalise_example_text(row.get("kw") or row.get("word"))
    right = _normalise_example_text(row.get("right"))
    text = _kwic_line(left, kw, right, row)
    if not text:
        return ""
    return _compact_text(
        f'kwic[{index}] "{text}"',
        KWIC_GROUNDING_QUOTE_LIMIT,
    )


def _metric_quote(index: int, row: Dict[str, Any]) -> str:
    parts: List[str] = []
    if row.get("word") not in (None, ""):
        parts.append(f"word={row.get('word')}")
    elif row.get("kw") not in (None, ""):
        parts.append(f"kw={row.get('kw')}")
    elif row.get("ngram") not in (None, ""):
        parts.append(f"ngram={row.get('ngram')}")
    for key in (
        "rank",
        "direction",
        "target_freq",
        "reference_freq",
        "diff_per_million",
        "f",
        "f2",
        "frequency",
        "freq",
        "n",
        "logdice",
        "mi3",
        "per_million",
        "p_value",
        "standard_deviation",
        "standard_error",
        "median",
        "score",
        "score_key",
        "mi",
        "t",
        "ll",
        "ll_signed",
        "q_value",
        "low_reliability",
        "dice",
        "chi2_cell",
        "delta_p_nc",
        "delta_p_cn",
        "lmi",
        "npmi",
        "z",
    ):
        if row.get(key) not in (None, ""):
            parts.append(f"{key}={row.get(key)}")
    if not parts:
        return ""
    return _compact_text(f"metric[{index}] {' '.join(parts)}", 220)


def _cluster_sample_values(cluster: Dict[str, Any]) -> List[str]:
    samples = cluster.get("samples")
    if isinstance(samples, dict):
        samples = samples.get("sample")
    if isinstance(samples, list):
        return [
            _normalise_example_text(sample)
            for sample in samples
            if _normalise_example_text(sample)
        ]
    sample_text = _normalise_example_text(samples)
    return [sample_text] if sample_text else []


def _cluster_is_informative(cluster: Any) -> bool:
    if not isinstance(cluster, dict):
        return False
    cluster_id = cluster.get("cluster_id", cluster.get("cluster"))
    if str(cluster_id).strip() == "-1":
        return False
    label = str(cluster.get("label") or "").strip().casefold()
    if label in {"", "misc", "other", "noise", "none", "unclustered"}:
        return False
    if _cluster_sample_values(cluster):
        return True
    size = cluster.get("size")
    try:
        return int(size) >= 2
    except Exception:
        return False


def _informative_clusters(raw_surface: Dict[str, Any]) -> List[Dict[str, Any]]:
    clusters = raw_surface.get("clusters")
    if not isinstance(clusters, list):
        return []
    return [cluster for cluster in clusters if _cluster_is_informative(cluster)]


_IDENTIFIER_METADATA_FIELD_RE = re.compile(
    r"(?:^|_)(?:id|uuid|hash|path|file|filename|url|uri)(?:_|$)",
    re.IGNORECASE,
)
_PARTITION_METADATA_FIELDS = frozenset(
    {"split", "fold", "partition", "dataset_split", "data_split"}
)


def _metadata_value_priority(
    field: Any,
    entries: Any,
    position: int,
) -> tuple[int, int, float, int]:
    """Prefer analytically useful, low-cardinality fields in bounded views."""

    field_name = str(field or "").strip()
    identifier_like = bool(_IDENTIFIER_METADATA_FIELD_RE.search(field_name))
    count = _count_or_sample_len(entries)
    try:
        numeric_count = max(0.0, float(count))
    except (TypeError, ValueError):
        numeric_count = float("inf")
    high_cardinality = numeric_count > 64
    return (
        int(identifier_like),
        int(high_cardinality),
        numeric_count,
        position,
    )


def _metadata_field_has_analytical_entries(field: Any, entries: Any) -> bool:
    """Exclude transport identifiers and empty fields from analysis context."""

    field_name = str(field or "").strip()
    if not field_name or _IDENTIFIER_METADATA_FIELD_RE.search(field_name):
        return False
    count = _count_or_sample_len(entries)
    if count is not None:
        try:
            return float(count) > 0
        except (TypeError, ValueError):
            pass
    return bool(_sample_items(entries)) or entries not in (None, "", [], {})


# Welche Methodenangabe unter welchem Namen in den Steckbrief geht, je
# Werkzeug. Die Quellen stehen als NAMEN da ("raw", "method", "args"), der
# Renderer loest sie gegen die Dikte des Postens auf.
#
# Als Datentabelle hier statt als Tupel-Literale mitten in
# ``_analysis_provenance_lines``: dieses Modul stand punktgenau auf seinem
# Zeilendeckel von 6000, und der Deckel verlangt ausdruecklich Zerlegung
# statt Anhebung. Die Tabelle ist Daten, nicht Ablauf, und gehoert neben
# die Extraktion, die die Namen ueberhaupt erst durchlaesst.
#
# Die letzten fuenf Zeilen der Voreinstellung sind P2.3: alle von den
# Werkzeugen geliefert und bis dahin verworfen. ``word_sketch`` meldet nur
# ``min_freq``, hatte damit NULL bits und fiel ueber
# "if not bits: continue" ganz aus dem Steckbrief. ``trend_analysis``, das
# der Plan als Muster fuer die uebrigen nennt, zeigte nur "Suche: und":
# ein Konfidenzintervall ohne Verfahren und Niveau ist eine Spanne ohne
# Bedeutung.
# Labels are LocalizedText: the German value is the str itself, the method
# sheet writes the English one in an English answer (answer_language.py).
_SUCHE = lt("Suche", "Search")
_ATTRIBUT = lt("Attribut", "Attribute")
_MINDESTFREQUENZ = lt("Mindestfrequenz", "Minimum frequency")
_ABFRAGEMODUS = lt("Abfragemodus", "Query mode")
_TREFFER = lt("Treffer", "Hits")

PROVENIENZ_VOREINSTELLUNG = (
    (_SUCHE, "query", ("raw", "args")),
    (_ATTRIBUT, "attribute", ("raw", "method", "args")),
    (lt("Einheit", "Unit"), "unit", ("raw",)),
    (_MINDESTFREQUENZ, "min_freq", ("raw", "method", "args")),
    (lt("Zeitfeld", "Date field"), "date_field", ("raw", "method", "args")),
    (lt("Granularität", "Granularity"), "granularity", ("raw", "method", "args")),
    (lt("Konfidenzverfahren", "Confidence method"), "ci_method", ("method", "raw")),
    (lt("Konfidenzniveau", "Confidence level"), "ci_level", ("method", "raw")),
)

_FALTUNG = (lt("Groß-/Kleinschreibung ignoriert", "Case ignored"), "case_insensitive", ("raw",))

PROVENIENZ_JE_WERKZEUG = {
    # Der Steckbrief nannte weder den analysierten Knoten noch den Korpus:
    # "Word Sketch: Mindestfrequenz: 3." allein sagt nicht, WOVON die Rede
    # ist. Beides liefert das Werkzeug, gerendert wurde keins.
    "word_sketch": (
        (lt("Knoten", "Node"), "term", ("raw", "args")),
        (_ATTRIBUT, "attribute", ("raw", "method", "args")),
        (_MINDESTFREQUENZ, "min_freq", ("raw", "method", "args")),
    ),
    "query_count": (
        (_ABFRAGEMODUS, "query_mode", ("raw",)),
        (_ATTRIBUT, "attribute", ("raw",)),
        _FALTUNG,
        (_SUCHE, "query", ("raw", "args")),
        (_TREFFER, "total", ("raw",)),
    ),
    "run_cqlf_query": (
        (_ABFRAGEMODUS, "query_mode", ("raw",)),
        (_ATTRIBUT, "attribute", ("raw",)),
        _FALTUNG,
        (_SUCHE, "query", ("raw", "args")),
        (lt("Kontextbreite", "Context width"), "ctx", ("raw", "args")),
        (lt("maximal angeforderte Zeilen", "maximum requested rows"), "limit", ("raw", "args")),
        (_TREFFER, "total", ("raw",)),
    ),
}


def rangliste_ausdruecklich_bestellt(evidence_items: Sequence[Any]) -> bool:
    """Check whether the call explicitly requested a frequency ranking.

    A POS filter, an explicit limit or a selected grouping identifies such
    a request. A frequency_list call alone may come from the deterministic
    plan and does not justify appending a ranking to every answer. When no
    term was counted, the caller decides whether the list itself is the answer.
    """
    for eintrag in evidence_items or ():
        if getattr(eintrag, "tool", None) != "frequency_list":
            continue
        flaeche = getattr(eintrag, "raw_surface", None) or {}
        try:
            args = json.loads(getattr(eintrag, "query", "") or "{}")
        except (TypeError, ValueError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        for schluessel in ("pos", "pos_filter", "limit", "top_n"):
            if flaeche.get(schluessel) or args.get(schluessel):
                return True
        gruppierung = flaeche.get("group_by") or args.get("group_by")
        if gruppierung and str(gruppierung).strip().casefold() != "word":
            return True
    return False


def zeilenbilanz(
    treffer: Any,
    zeilen: Any,
    formatiere: Callable[[Any], str],
) -> str:
    """Wie sich die zurueckgegebenen Zeilen zur Trefferzahl verhalten.

    Die Provenienzzeile trug beide Groessen als gleichrangige Glieder
    derselben Komma-Reihe. Wo sie zusammenfielen, las sich das wie ein
    Tippfehler: „Treffer: 3, 3 zurueckgegebene Ergebniszeilen“. Wo sie
    auseinanderfielen, stand die eigentliche Nachricht ungesagt daneben,
    naemlich dass gekappt wurde.

    Nur ``run_cqlf_query`` kann heute ueberhaupt beides tragen, weil nur
    dieses Werkzeug zugleich einen ``Treffer``-Eintrag in
    ``PROVENIENZ_JE_WERKZEUG`` und einen Zeilenschluessel besitzt. Ohne
    Trefferzahl bleibt der bisherige Wortlaut unveraendert stehen, denn
    dort ist die Zeilenzahl die einzige Angabe und traegt ihre Bedeutung
    allein.
    """

    def _zahl(wert: Any) -> float | None:
        if isinstance(wert, bool) or wert in (None, ""):
            return None
        try:
            return float(wert)
        except (TypeError, ValueError):
            return None

    a, b = _zahl(treffer), _zahl(zeilen)
    if a is None or b is None:
        return formatiere(zeilen) + _t(" zurückgegebene Ergebniszeilen", " result rows returned")
    if a == b:
        return _t("alle als Ergebniszeilen zurückgegeben", "all returned as result rows")
    return _t("davon {} als Ergebniszeilen zurückgegeben", "{} of them returned as result rows").format(
        formatiere(zeilen))


# Welche Zeilen der Evidenzflaeche ein woertliches Zitat decken duerfen.
#
# Die Regel liegt hier statt in recipe_runtime, weil ZWEI Konsumenten sie
# brauchen: die Zitatwache am Antwort-Chokepoint und die Faktenbildung,
# die ``grounding_quotes`` aus ``item.grounding_surface[:1]`` schoepft und
# von dort in ``grounding_validation.quote_surfaces`` weiterreicht. Der
# zweite Weg war ungeschuetzt, und die Selbstdeckung des Modells kam
# darueber zurueck.
_INHALT_TRAGENDE_FELDER = frozenset({
    "snippet", "text", "example", "context", "left", "kw", "right", "match",
})
# Auch GEPUNKTETE und GEKLAMMERTE Koepfe. Eine Vorfassung verlangte einen
# nackten Bezeichner, und ``diagnostics.requested_fields=[...]`` rutschte
# durch. Gemessen: metadata_values spiegelt einen FREI WAEHLBAREN
# Feldnamen woertlich zurueck, und damit deckte das Modell seine eigene
# Erfindung erneut selbst.
# Ein Kopf ist ein Pfad aus Bezeichnern, Punkten und Klammern, direkt
# gefolgt von "=" oder ": ". Der Pfad darf KEIN Leerzeichen und keine
# geschweifte Klammer enthalten, sonst frisst der Ausdruck
# "rows[0] {'kw': ...}", und das IST Inhalt.
_PFAD = r"[A-Za-z_][A-Za-z0-9_]*(?:[.\[][A-Za-z0-9_'\"\].]*)*"
# KEIN Leerraum vor dem Trenner. Gerenderte Skalare heissen "name=wert"
# oder "name: wert", KWIC-Text traegt Leerzeichen um seine Satzzeichen.
# Mit erlaubtem Leerraum strich die Regel echte Korpuszeilen, deren
# linker Kontext auf ein einzelnes Wort endete:
#     "Klima : Die Debatte war hitzig ."   verlor seinen Beleg
#     "Wort = Zeichen in diesem Satz ."    ebenso
# Das ist die gefaehrlichere Richtung: eine Wache, die echte Belege
# streicht, entkernt die Antwort und etikettiert Korpustext als Fabrikat.
_SKALARE_KOPFZEILE = re.compile(rf"^{_PFAD}(?:=|:\s)")

# Die Schluessel der Werkzeugausgaben, unter denen KORPUSINHALT steht.
INHALT_SCHLUESSEL = (
    "rows", "examples", "snippets", "matches", "concordance", "sample",
    "kwic", "lines", "hits", "documents", "passages",
    # Volltext und KWIC-Felder auf der OBERSTEN Ebene. Eine Vorfassung
    # dieser Liste kannte sie nicht, und document_text lieferte NULL
    # Belegzeilen: jedes woertliche Volltext-Zitat waere gestrichen
    # worden. Eine Wache, die echte Belege entfernt, ist so schaedlich
    # wie eine, die Fabrikate durchlaesst, und diese Richtung faellt
    # niemandem auf, der nur nach Fabrikaten sucht.
    "text", "content", "body", "full_text", "snippet", "context",
    "left", "kw", "right", "match", "example",
)


# Tools whose output can establish literal corpus quotations.
# Check provenance rather than rendered appearance: clustering can echo
# input text, and documentation search reads the manual rather than the corpus.
# Use an allowlist so new tools require an explicit provenance decision.
# The registry comparison in test_quote_guard_provenance keeps it current.
KORPUSLESENDE_WERKZEUGE = frozenset({
    "run_cqlf_query", "kwic_context", "document_text", "document_search",
    "semantic_search", "parallel_kwic", "parallel_groups",
    "ngram_frequency", "ngram_contrast", "frequency_list",
    "collocate_stats", "collocation_network", "contrast_collocates",
    "compare_collocates", "keyness", "word_sketch", "similar_words",
    "trend_analysis", "dispersion_offsets", "query_count",
    "lexical_diversity", "create_docset", "list_docsets",
    "metadata_values", "resolve_subcorpus",
})

#: Werkzeuge, die AUSDRUECKLICH keinen Korpusbeleg liefern. Nur zur
#: Vollstaendigkeitspruefung gegen die Registry, das Verhalten haengt allein
#: an der Erlaubnisliste oben.
NICHT_KORPUSLESENDE_WERKZEUGE = frozenset({
    # Liest das Handbuch dieser Software.
    "documentation_search",
    # Arbeiten auf den vom Modell uebergebenen Tokens und Etiketten, nicht
    # auf dem Korpus. Genau hier lief der Selbstdeckungs-Angriff.
    "semantic_cluster", "semantic_cluster_words", "semantic_recluster",
    "refine_cluster_label", "cluster_export_md", "cluster_save",
    # Erklaert das Ende der Werkzeugphase. Beruehrt das Korpus nicht und darf
    # deshalb nie ein woertliches Korpuszitat decken.
    "deutung_abgeben",
})


def werkzeug_liefert_korpusbeleg(name: Any) -> bool:
    """Darf eine Zeile DIESES Werkzeugs ein woertliches Korpuszitat decken?"""
    return str(name or "").strip() in KORPUSLESENDE_WERKZEUGE


def traegt_korpusinhalt(zeile: str) -> bool:
    """Darf diese Belegzeile ein woertliches Zitat decken?

    KWIC-Zusammensetzungen, ``rows[i] {...}`` und Beispieltexte ja,
    ``name=wert``-Skalare nein, ausser den wenigen, die selbst Korpustext
    fuehren. Skalare wiederholen Parameter, Zustaende und Echos der
    Eingabe, und genau darueber deckte das Modell seine eigene Erfindung.
    """
    roh = str(zeile or "")
    treffer = _SKALARE_KOPFZEILE.match(roh)
    if not treffer:
        return True
    # IRGENDEIN Pfadsegment entscheidet: "sample.text=" und "match[0]="
    # tragen Inhalt, "diagnostics.requested_fields=" und "values.source="
    # nicht. Nur das letzte Segment zu pruefen war zu eng, weil ein Index
    # dahinterstehen kann.
    kopf = roh[: treffer.end() - 1].strip().rstrip(":")
    segmente = {s.strip("]' \"") for s in re.split(r"[.\[]", kopf)}
    return bool(segmente & _INHALT_TRAGENDE_FELDER)


def _kurzer_indexstand(signatur: str) -> str:
    """Die Indexsignatur als zwoelfstelliger Hash statt als Dateipfad.

    Eine Weiterleitung auf ``analysis_defaults.kurzer_indexstand``, damit
    Copilot-Naht und REST-Naht fuer denselben Index BYTE-GLEICH denselben
    Wert melden. Zwei eigene Kopien haetten genau das nicht garantiert.
    """
    from candyconc.analysis_defaults import kurzer_indexstand

    return kurzer_indexstand(signatur)


def werkzeugausgabe_ohne_betreiberpfad(out: Any) -> Any:
    """Den Indexstand einer Werkzeugausgabe hashen, bevor sie den Prozess verlaesst.

    ``build_method_block`` fuehrt ihn als ``<absoluter Pfad>@<mtime_ns>``.
    Die ROHE Werkzeugausgabe speist im Orchestrator drei Verbraucher aus
    EINER Variablen: den Evidenzposten, das SSE-Ereignis
    ``copilot.tool_result`` und das Lineage-Log ueber
    ``project.add_ai_output``. Gehasht wurde bisher nur die erste, und das
    Heimatverzeichnis des Betreibers stand weiter im Ereignisstrom und im
    Projektprotokoll.

    Deshalb hier, an der Stelle, an der die Ausgabe entsteht: EIN Aufruf
    deckt alle drei. Nicht in ``build_method_block`` selbst, weil die
    REST-Provenienz die volle Signatur fuehrt und ein bestehender Test sie
    dort woertlich pinnt (``"idx@123"``).

    Der Hash leistet, was die Angabe leisten soll: gleicher Index gleicher
    Wert, neu gebauter Index anderer Wert. Die Ausgabe wird nur kopiert,
    wenn wirklich etwas zu ersetzen ist.
    """
    if not isinstance(out, dict):
        return out
    block = out.get("method")
    if not isinstance(block, dict):
        return out
    ersetzt = {
        s: _kurzer_indexstand(str(block[s]))
        for s in ("indexFingerprint", "index_fingerprint")
        if str(block.get(s) or "").strip()
    }
    if not ersetzt:
        return out
    return {**out, "method": {**block, **ersetzt}}


# Number of diagnostic entries shown to the model.
# Keep declared denominators, context coverage, POS and case policy visible
# together. Unbounded fact recording retains all diagnostics.
DIAGNOSTIK_SICHTBAR = 14


def extract_raw_surface(
    output: Any,
    *,
    bounded: bool = True,
    werkzeug: str | None = None,
) -> Dict[str, Any]:
    """``werkzeug`` waehlt den Feldvertrag der Zeilenoberflaeche.

    Ohne Namen gilt die gemeinsame Vorzugsliste. Das ist fuer Werkzeuge
    ohne eigene Methoden-Invarianten richtig, waere aber ein stiller
    Rueckfall, wenn eine Naht den Namen nicht durchreicht. Deshalb zaehlt
    ``test_field_contract_reaches_every_seam`` die Aufrufstellen aus.
    """
    if not isinstance(output, dict):
        return {"value": _compact_text(output, 220)}
    surface: Dict[str, Any] = {}
    for key in (
        "status",
        "message",
        "level",
        "total",
        "bereich",
        "rows_total",
        # Die gelieferten KWIC-Zeilen nach der Achse, die Fassungen unterscheidet,
        # gesetzt an der Naht des Orchestrators (version_distribution).
        "verteilung",
        "query",
        "query_mode",
        "attribute",
        "case_insensitive",
        "faltung_teilweise",
        "ctx",
        "limit",
        "per_million",
        "p_value",
        "standard_deviation",
        "standard_error",
        "median",
        "corpus_tokens",
        "denominator_tokens",
        "denominator_tokens_raw",
        "denominator_scope",
        "denominator_source",
        "requested_term",
        "effective_term",
        "term_mode",
        "window",
        "within_sentence",
        "sort_by",
        "min_freq",
        "node_frequency",
        "result_count",
        "group_by",
        "pos",
        "label",
        "unit",
        "dp",
        "dpnorm",
        "dp_min",
        "dp_erwartet",
        "dp_max",
        "juilland_d",
        "carroll_d2",
        "range",
        "range_prop",
        "vc",
        "profile",
        "total_hits",
        "n_documents",
        "coverage_ratio",
        "nonzero_partitions",
        "peak_partition",
        "peak_share",
        "docset_id",
        # Die beiden Kontrastseiten. Ohne sie ist aus der Evidenz nicht
        # rekonstruierbar, welche Seite welche ist, und der deterministische
        # Verfasser schrieb "Seite A"/"Seite B" (siehe grounding_contrast).
        "target_docset_id",
        "reference_docset_id",
        # Das Etikett des Docsets, aus dem der Verfasser die Seite benennt.
        "label",
        "doc_count",
        "token_count",
        "word_count",
        "source",
        "doc_id",
        "left",
        "kw",
        "match",
        "match_tokens",
        "match_offsets",
        "right",
        "date_field",
        "granularity",
        "periods_total",
        "ttr",
        "sttr",
        "sttr_window",
        "sttr_n_windows",
        "mattr",
        "mattr_window",
        "guiraud",
        "n_tokens",
        "n_types",
        "corpus_raw_token_count",
        "analyst_tokens_only",
        "analyst_token_policy",
        # Der Volltext eines Dokuments. Er stand NICHT auf dieser Liste,
        # und damit war jedes woertliche Zitat aus document_text
        # unbelegt: die Zitatwache strich es, weil die Evidenzflaeche den
        # Text gar nicht fuehrte (nur status, doc_id, token_count). Ein
        # Konkordanzer, dem man den Dokumenttext zeigt, muss daraus
        # zitieren duerfen.
        "text",
        # P2.3: das n einer n-Gramm-Auswertung. ngram_frequency liefert
        # min_n und max_n, diese Liste hat beide gestrichen, und eine
        # n-Gramm-Zahl ohne n ist nicht einzuordnen.
        "min_n",
        "max_n",
        "populations",
        # Die Schreibungen einer gefalteten Zaehlung (daß/dass). Kandidat 4,
        # Frage 10: das Modell sah sie, das Paket nicht, und die Synthese
        # erfuhr nicht, dass 551.103 Treffer fuer „daß“ fast alle „dass“ sind.
        "schreibung_gefaltet",
        "mit_c",
        "andere_schreibung",
        "nach",
        "dp_nach",
        "dp_norm_nach",
        "dp_min_nach",
        "dp_erwartet_nach",
        "docs_with_hits",
        "source_texts_with_hits",
        "per_million_ci",
        "ci_cluster",
        "bestandteile_masse",
        "bestandteile_anteil",
        "bestandteile_muster",
        # collocate_stats, Leerumschlag: warum nichts gemessen wurde.
        "diagnosis",
        "schwelle_gebunden",
        # keyness: gelieferte Zeilen und das Sortiermaß der Tabelle.
        "rows_returned",
        "sortiert_nach",
        # Absagen und Grenzen (compare_collocates, parallel_*, similar_words).
        "reason",
        "feature",
        "detail",
        "code",
        "backend",
        # Die Suchform einer Dispersion, eines Netzes, eines Thesaurus.
        "term",
        "measure",
        # dispersion_offsets im Fensterrückfall.
        "partitions",
        "positional_dp_windowed",
        # Cluster, Teilkorpus, Paarung, Dokument.
        "input_token_count",
        "cluster_token_count",
        "cluster_id",
        "name",
        "corpus",
        "ref_doc",
        "base_doc_id",
        "char_count",
        "url",
    ):
        if output.get(key) not in (None, "", [], {}):
            surface[key] = output.get(key)
    for nested_key, allowed_keys in (
        (
            "scope",
            ("corpus_id", "level", "docset_id", "doc_count"),
        ),
        (
            "method",
            (
                "attribute",
                "window",
                "within_sentence",
                "sort_by",
                "min_freq",
                # P2.3: Herkunft des Mindestfrequenz-Bodens. Ohne diesen
                # Namen faellt der Wert hier heraus und erreicht den
                # Methodensteckbrief nie.
                "floor_mode",
                # P2.3: der Indexstand an seiner QUELLE. trend_analysis
                # berechnet ihn ueber build_method_block, und diese Liste
                # hat ihn gestrichen -- zusammen mit dem GANZEN uebrigen
                # Block, denn keiner der bis dahin erlaubten sechs Namen
                # kommt in trend_analysis vor. Das Werkzeug, das der Plan
                # als Muster fuer die uebrigen nennt, erreichte den
                # Steckbrief deshalb mit null Methodenangaben.
                "indexFingerprint",
                "index_fingerprint",
                # Die inferentielle Provenienz einer Trendaussage. Ein
                # Konfidenzintervall ohne Verfahren und Niveau ist eine
                # Spanne ohne Bedeutung.
                "ci_method",
                "ci_level",
            ),
        ),
        (
            "sample",
            (
                "requested",
                "drawn",
                "seed",
                "population",
                "population_partial",
                "method",
                # Die Zeilen stehen in Ziehungsfolge, nicht nach Korpusposition.
                "order",
            ),
        ),
    ):
        nested = output.get(nested_key)
        if isinstance(nested, dict):
            cleaned = {
                key: nested[key]
                for key in allowed_keys
                if nested.get(key) not in (None, "", [], {})
            }
            # Der Indexstand kommt als "<absoluter Pfad>@<mtime_ns>" aus
            # build_method_block. Roh gehoert er NICHT in diese Flaeche:
            # sie wird als grounding_surface in den Modellkontext
            # gerendert, und dort stand dann
            # "method: indexFingerprint=/Users/<name>/..." -- das
            # Heimatverzeichnis des Betreibers, gemessen an
            # trend_analysis. Der Hash leistet dasselbe: gleicher Index
            # gleicher Wert, neu gebauter Index anderer Wert. Er wird
            # HIER gebildet, damit der Wert nachweislich von dem Index
            # stammt, auf dem das Werkzeug gerechnet hat.
            for schluessel in ("indexFingerprint", "index_fingerprint"):
                roh = str(cleaned.get(schluessel) or "").strip()
                if roh:
                    cleaned[schluessel] = _kurzer_indexstand(roh)
            if cleaned:
                surface[nested_key] = cleaned
    if output_is_truncated(output):
        surface["truncated"] = True
    if output_is_partial(output):
        surface["partial"] = True
    if output_is_sampled(output):
        surface["sampled"] = True
    rows = output.get("rows")
    rows_seen = _count_or_sample_len(rows)
    if rows_seen is not None:
        surface["rows_seen"] = rows_seen
    row_samples = _sample_items(rows)
    if row_samples:
        method = output.get("method")
        selected_metric = output.get("sort_by")
        if (
            selected_metric in (None, "")
            and isinstance(method, dict)
        ):
            selected_metric = method.get("sort_by")
        sicht = min(len(row_samples), SICHT_ZEILEN_REISSLEINE)
        nummern = list(range(len(row_samples)))
        if bounded:
            from candyconc.candyconc_copilot.version_distribution import KWIC_WERKZEUGE
            from candyconc.candyconc_copilot.sample_order import liegt_in_ziehungsfolge

            nummern, grounding_selection = _grounding_row_indices(
                row_samples,
                limit=sicht,
                sortiert_nach=str(output.get("sortiert_nach") or selected_metric or ""),
                # KWIC-Listen und Stichproben in einer Sortierung verteilt über die
                # ganze Liste (view_row_selection). In Ziehungsfolge ist schon der Anfang
                # gleichverteilt und zeigt dieselben Zeilen wie Aufzeichnung und Paket.
                gleichmaessig=(str(werkzeug or "") in KWIC_WERKZEUGE or output_is_sampled(output))
                and not liegt_in_ziehungsfolge(output),
            )
            if grounding_selection:
                surface["grounding_selection"] = grounding_selection
        from candyconc.candyconc_copilot.view_row_selection import mit_pfad

        # Ist die Auswahl kein Anfang der Liste, nennt jede Zeile ihren Pfad im
        # Werkzeugergebnis, damit rows[i] überall dieselbe Zeile meint.
        surface["rows"] = mit_pfad([
            _surface_row_dict(
                row_samples[nummer],
                limit_keys=8 if bounded else None,
                required_keys=(
                    [str(selected_metric)]
                    if selected_metric not in (None, "")
                    else []
                ),
                werkzeug=werkzeug,
            )
            for nummer in nummern
        ], nummern)
        if bounded and len(row_samples) > sicht:
            surface["grounding_truncated"] = True
            surface["grounding_rows_total"] = len(row_samples)
            surface["grounding_rows_visible"] = sicht
    periods = output.get("periods")
    period_samples = _sample_items(periods)
    if period_samples:
        # AUSGEDUENNT, nicht abgeschnitten. Dieser Schnitt bestimmt, was das
        # Modell wirklich sieht, und ein Kopfschnitt liesse von einer Reihe
        # 1949 bis 2021 die Jahre 1949 bis 1968 uebrig. Siehe
        # tool_wrappers.gleichmaessige_auswahl, dieselbe Politik wie beim
        # ersten Schnitt, damit die beiden Schnitte nicht gegeneinander
        # arbeiten.
        if bounded and len(period_samples) > DEFAULT_GROUNDING_ROW_LIMIT:
            from candyconc.analysis_defaults import perioden_ausduennen

            visible_periods = perioden_ausduennen(
                period_samples, DEFAULT_GROUNDING_ROW_LIMIT
            )
        else:
            visible_periods = period_samples
        surface["periods"] = [
            _surface_row_dict(
                period,
                limit_keys=8 if bounded else None,
            )
            for period in visible_periods
        ]
        if bounded and len(period_samples) > DEFAULT_GROUNDING_ROW_LIMIT:
            # BEZIFFERT. Der Zeilen-Zweig zehn Zeilen weiter oben nennt seine
            # Zahlen seit jeher, dieser Zweig setzte nur die Flagge. Daneben
            # stand weiter die Warnung des Werkzeugs mit "60 von 73", waehrend
            # das Modell 20 sah: eine Zahl ueber die eigene Evidenz, die um den
            # Faktor drei falsch war.
            surface["grounding_truncated"] = True
            surface["grounding_periods_total"] = len(period_samples)
            surface["grounding_periods_visible"] = len(visible_periods)
    warnings = output.get("warnings")
    if isinstance(warnings, list) and warnings:
        surface["warnings"] = [
            _compact_text(item, 220)
            for item in (warnings[:8] if bounded else warnings)
            if str(item or "").strip()
        ]
    semantic_meta = _surface_semantic_meta(output.get("meta"))
    if semantic_meta:
        surface["meta"] = semantic_meta
    elif str(werkzeug or "") in ("document_text", "kwic_context") and isinstance(output.get("meta"), dict):
        # Die Metadaten des gelesenen Dokuments (Register, Modell, Quelle). Ohne
        # sie war ein Zitat aus document_text in der Aufzeichnung keiner Fassung
        # zuzuordnen.
        surface["meta"] = {
            str(k): v for k, v in output["meta"].items()
            if isinstance(v, (str, int, float, bool)) and v not in ("", None)
        }
    # Ergebnislisten ohne eigene Zeilensicht: nur in der Belegaufzeichnung, damit
    # Paket und Zahlendeckung sie kennen. Die begrenzte Sicht bleibt, wie sie war.
    # Eine Liste von bis zu 200 Einträgen hätte die kompakte Modellsicht über
    # ihre Zeichengrenze gehoben und in die Zeilenform gekippt
    # (orchestrator._tool_output_for_model). Eine Zeilensicht für diese Listen
    # ist offen.
    for schluessel in ("neighbours", "variants", "groups", "nodes", "edges", "subcorpora"):
        liste = output.get(schluessel)
        if not bounded and isinstance(liste, list) and liste:
            surface[schluessel] = list(liste)
    tables = output.get("tables")
    if isinstance(tables, dict) and tables:
        surface_tables: Dict[str, Any] = {}
        table_items = list(tables.items())
        if bounded:
            table_items = table_items[:6]
        for table_name, entries in table_items:
            if isinstance(entries, list):
                visible_entries = entries[:6] if bounded else entries
                surface_tables[str(table_name)] = [
                    _surface_row_dict(
                        entry,
                        limit_keys=8 if bounded else None,
                        required_keys=[
                            str(entry.get("score_key"))
                        ]
                        if isinstance(entry, dict)
                        and entry.get("score_key") not in (None, "")
                        else (),
                    )
                    for entry in visible_entries
                ]
                if bounded and len(entries) > 6:
                    surface["grounding_truncated"] = True
            else:
                surface_tables[str(table_name)] = _compact_text(entries, 160)
        surface["tables"] = surface_tables
    relations = output.get("relations")
    if isinstance(relations, dict) and relations:
        surface_relations: Dict[str, Any] = {}
        relation_items = list(relations.items())
        if bounded:
            relation_items = relation_items[:8]
        for relation_name, metadata in relation_items:
            if isinstance(metadata, dict):
                surface_relations[str(relation_name)] = {
                    str(key): value
                    for key, value in metadata.items()
                    if key
                    in {
                        "relation",
                        "label",
                        "row_limit",
                        "total_candidates",
                        "total_rows",
                        "truncated",
                        "min_freq",
                        "basis",
                        "coverage_scope",
                    }
                    and value not in (None, "", [], {})
                }
            else:
                surface_relations[str(relation_name)] = _compact_text(metadata, 160)
        if surface_relations:
            surface["relations"] = surface_relations
    offsets = output.get("offsets")
    if isinstance(offsets, list) and offsets:
        surface["offsets"] = list(offsets[:16] if bounded else offsets)
    clusters = output.get("clusters")
    clusters_seen = _count_or_sample_len(clusters)
    if clusters_seen is not None:
        surface["clusters_seen"] = clusters_seen
    cluster_samples = _sample_items(clusters)
    if cluster_samples:
        visible_clusters = cluster_samples[:4] if bounded else cluster_samples
        surface["clusters"] = [
            _surface_cluster_dict(cluster, limit_keys=6)
            for cluster in visible_clusters
        ]
        if bounded and len(cluster_samples) > 4:
            surface["grounding_truncated"] = True
    fallback = output.get("fallback")
    if isinstance(fallback, dict) and fallback:
        surface["fallback"] = {
            key: _compact_text(value, 220)
            for key, value in fallback.items()
            if key in {"requested_level", "used_level", "reason"}
            and value not in (None, "", [], {})
        }
    diagnostics = output.get("diagnostics")
    if isinstance(diagnostics, dict) and diagnostics:
        surface_diagnostics: Dict[str, Any] = {}
        diagnostic_items = list(diagnostics.items())
        if bounded:
            diagnostic_items = diagnostic_items[:DIAGNOSTIK_SICHTBAR]
        for key, value in diagnostic_items:
            if isinstance(value, list):
                surface_diagnostics[str(key)] = [
                    _normalise_example_text(item)
                    for item in (value[:8] if bounded else value)
                    if _normalise_example_text(item)
                ]
            elif isinstance(value, (str, int, float, bool)) or value is None:
                surface_diagnostics[str(key)] = value
            else:
                surface_diagnostics[str(key)] = _compact_text(value, 120)
        if surface_diagnostics:
            surface["diagnostics"] = surface_diagnostics
    plan = output.get("plan")
    if isinstance(plan, dict) and plan:
        surface["plan"] = _surface_row_dict(plan, limit_keys=6)
    available_fields = output.get("available_fields")
    available_field_items = _sample_items(available_fields)
    if available_field_items:
        if bounded and len(available_field_items) > 32:
            surface["available_fields_truncated"] = True
        surface["available_fields"] = [
            _normalise_example_text(field)
            for field in (
                available_field_items[:32]
                if bounded
                else available_field_items
            )
            if _normalise_example_text(field)
        ]
    values = output.get("values")
    if isinstance(values, dict) and values:
        surface_values: Dict[str, Any] = {}
        value_counts: Dict[str, int] = {}
        identifier_value_fields: List[str] = []
        sampled_value_fields: List[str] = []
        # H6 (B4): Zaehler fuer ALLE Felder des Tool-Outputs VOR dem
        # Analytik-Filter erheben. Der Filter entfernt Identifier-Felder
        # (doc_id, path, reference_hash, ...) aus den sichtbaren
        # Wertelisten. Ohne die Zaehler ginge die Information "Feld hat
        # N Werte" downstream verloren und der Renderer wuerde die
        # Filterung faelschlich als Tool-Leere formulieren. Nur Zaehler,
        # keine Wertelisten, die Surface bleibt bounded.
        for raw_field, entries in values.items():
            field_name = _normalise_example_text(raw_field)
            if not field_name:
                continue
            count = _count_or_sample_len(entries)
            if count in (None, ""):
                continue
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                continue
            value_counts[field_name] = count_int
            if count_int > 0 and _IDENTIFIER_METADATA_FIELD_RE.search(
                str(raw_field or "").strip()
            ):
                identifier_value_fields.append(field_name)
        ordered_values = sorted(
            enumerate(values.items()),
            key=lambda item: _metadata_value_priority(
                item[1][0],
                item[1][1],
                item[0],
            ),
        )
        analytical_values = [
            item
            for item in ordered_values
            if _metadata_field_has_analytical_entries(item[1][0], item[1][1])
        ]
        if bounded and len(analytical_values) > 12:
            surface["grounding_truncated"] = True
        visible_values = analytical_values[:12] if bounded else analytical_values
        for _, (field, entries) in visible_values:
            field_name = _normalise_example_text(field)
            if not field_name:
                continue
            count = value_counts.get(field_name)
            entry_samples = _sample_items(entries)
            if entry_samples:
                # Felder mit bis zu 50 Werten ganz: variant hat 13 Werte, und
                # die Kappung bei 12 liess genau Teuken weg, das einzige Modell,
                # das in r3b-spiegel-1 die Register kippt (Pruefer Ablauf,
                # Zyklus 8). Gekappt bleiben Kennungsfelder mit vielen Werten.
                visible_entry_samples = (
                    entry_samples[:12]
                    if bounded and len(entry_samples) > 50
                    else entry_samples
                )
                cleaned = [
                    _normalise_example_text(entry)
                    for entry in visible_entry_samples
                    if _normalise_example_text(entry)
                ]
                if cleaned:
                    surface_values[field_name] = cleaned
                try:
                    sample_is_partial = count is not None and float(count) > len(cleaned)
                except (TypeError, ValueError):
                    sample_is_partial = len(entry_samples) > 8
                if sample_is_partial:
                    sampled_value_fields.append(field_name)
            elif not isinstance(entries, dict):
                compact = _compact_text(entries, 120)
                if compact:
                    surface_values[field_name] = compact
        if surface_values:
            surface["values"] = surface_values
        if value_counts:
            surface["value_counts"] = value_counts
        if identifier_value_fields:
            surface["identifier_value_fields"] = identifier_value_fields
        if sampled_value_fields:
            surface["sampled_value_fields"] = sampled_value_fields
    return surface


def build_grounding_surface(raw_surface: Dict[str, Any]) -> List[str]:
    if not isinstance(raw_surface, dict):
        return []
    lines: List[str] = []
    for key in (
        "status",
        "message",
        "level",
        "total",
        "rows_total",
        "query",
        "query_mode",
        "attribute",
        "case_insensitive",
        "faltung_teilweise",
        "ctx",
        "limit",
        "per_million",
        "p_value",
        "standard_deviation",
        "standard_error",
        "median",
        "corpus_tokens",
        "denominator_tokens",
        "denominator_tokens_raw",
        "denominator_scope",
        "denominator_source",
        "requested_term",
        "effective_term",
        "term_mode",
        "window",
        "within_sentence",
        "sort_by",
        "min_freq",
        "node_frequency",
        "result_count",
        "group_by",
        "pos",
        "rows_seen",
        "grounding_rows_total",
        "grounding_rows_visible",
        "grounding_selection",
        "clusters_seen",
        "label",
        "truncated",
        "partial",
        "sampled",
        "grounding_truncated",
        "unit",
        "dp",
        "dpnorm",
        # Include the reference values used to classify dispersion.
        # The model needs them alongside the observed DP and profile label.
        "dp_min",
        "dp_erwartet",
        "dp_max",
        "juilland_d",
        "carroll_d2",
        "range",
        "range_prop",
        "vc",
        "profile",
        "total_hits",
        "n_documents",
        "coverage_ratio",
        "nonzero_partitions",
        "peak_partition",
        "peak_share",
        "docset_id",
        # Die beiden Kontrastseiten. Ohne sie ist aus der Evidenz nicht
        # rekonstruierbar, welche Seite welche ist, und der deterministische
        # Verfasser schrieb "Seite A"/"Seite B" (siehe grounding_contrast).
        "target_docset_id",
        "reference_docset_id",
        # Das Etikett des Docsets, aus dem der Verfasser die Seite benennt.
        "label",
        "doc_count",
        "token_count",
        "word_count",
        "source",
        "doc_id",
        "left",
        "kw",
        "right",
        "date_field",
        "granularity",
        "periods_total",
        "ttr",
        "sttr",
        "sttr_window",
        "sttr_n_windows",
        "mattr",
        "mattr_window",
        "guiraud",
        "n_tokens",
        "n_types",
        "corpus_raw_token_count",
        "analyst_tokens_only",
        "analyst_token_policy",
        # Die Nenner der n-Gramm-Raten je Ordnung (siehe extract_raw_surface).
        # Erst als Belegzeile gilt eine zitierte Stellenzahl als belegt.
        "populations",
        "schreibung_gefaltet",
        "mit_c",
        "andere_schreibung",
        # Preserve the breakdown's dispersion values in the evidence package.
        "nach",
        "dp_nach",
        "dp_norm_nach",
        "dp_min_nach",
        "dp_erwartet_nach",
        "docs_with_hits",
        "source_texts_with_hits",
        "per_million_ci",
        "ci_cluster",
        # Keep response fields available to evidence recording, packaging and
        # number support checks. The response-schema comparison verifies coverage.
        # query_count also reports compound-type contributions excluded from total.
        "bestandteile_masse",
        "bestandteile_anteil",
        "bestandteile_muster",
        # collocate_stats, Leerumschlag: warum nichts gemessen wurde.
        "diagnosis",
        "schwelle_gebunden",
        # keyness: gelieferte Zeilen und das Sortiermaß der Tabelle.
        "rows_returned",
        "sortiert_nach",
        # Absagen und Grenzen (compare_collocates, parallel_*, similar_words).
        "reason",
        "feature",
        "detail",
        "code",
        "backend",
        # Die Suchform einer Dispersion, eines Netzes, eines Thesaurus.
        "term",
        "measure",
        # dispersion_offsets im Fensterrückfall.
        "partitions",
        "positional_dp_windowed",
        # Cluster, Teilkorpus, Paarung, Dokument.
        "input_token_count",
        "cluster_token_count",
        "cluster_id",
        "name",
        "corpus",
        "ref_doc",
        "base_doc_id",
        "char_count",
        "url",
    ):
        if key in raw_surface:
            lines.append(_compact_text(f"{key}={raw_surface[key]}", 220))
    for nested_key in ("scope", "method", "sample"):
        nested = raw_surface.get(nested_key)
        if isinstance(nested, dict) and nested:
            rendered = ", ".join(
                f"{key}={value}" for key, value in nested.items()
            )
            lines.append(_compact_text(f"{nested_key}: {rendered}", 220))
    if raw_surface.get("kw") not in (None, ""):
        kwic_line = _kwic_quote(1, raw_surface)
        if kwic_line:
            lines.append(kwic_line)
    # Im Wortlaut der Modellsicht und vor den Zeilen, damit Sicht und Paket
    # dieselbe Angabe zeigen und keine Kappe sie hinter die Zeilen schiebt.
    if raw_surface.get("verteilung") not in (None, ""):
        lines.append(str(raw_surface["verteilung"]))
    # Ebenso ungekürzt und vor den Zeilen: die Angabe enthält die within-Form der
    # Abfrage, und die 220 Zeichen der Schlüsselzeilen schnitten sie ab.
    if raw_surface.get("bereich") not in (None, ""):
        lines.append(f"bereich={raw_surface['bereich']}")
    rows = raw_surface.get("rows")
    if isinstance(rows, list):
        from candyconc.candyconc_copilot.view_row_selection import ohne_pfad, zeilennummer

        for platz, row in enumerate(
            rows[:SICHT_ZEILEN_REISSLEINE],
            # H11.8: ab 0, wie der Resolver indexiert.
            start=0,
        ):
            # Eine verteilte Auswahl trägt je Zeile ihren Pfad, er ist die Beschriftung.
            index, row = zeilennummer(row, platz), ohne_pfad(row)
            if isinstance(row, dict):
                match_span = _normalise_example_text(row.get("match"))
                if match_span:
                    lines.append(
                        _compact_text(
                            f'match[{index}]="{match_span}"',
                            KWIC_GROUNDING_QUOTE_LIMIT,
                        )
                    )
                row_line = _row_quote("rows", index, row)
                if row_line:
                    lines.append(row_line)
                if (
                    row.get("rank") in (None, "")
                    and not any(
                        row.get(key) not in (None, "")
                        for key in ("left", "right", "snippet")
                    )
                    and any(
                        row.get(key) not in (None, "")
                        for key in (
                            "f",
                            "frequency",
                            "freq",
                            "per_million",
                            "score",
                            "ll",
                            "logdice",
                            "ngram",
                        )
                    )
                ):
                    lines.append(f"rank={index}")
                for key in (
                    "word",
                    "kw",
                    "doc_id",
                    "score",
                    "freq_human",
                    "freq_ai",
                    "freq_target",
                    "freq_reference",
                    "chi2_cell_human",
                    "chi2_cell_ai",
                    "chi2_cell_target",
                    "chi2_cell_reference",
                    "log_ratio",
                    "log_ratio_ci_low",
                    "log_ratio_ci_high",
                    "target_per_million",
                    "reference_per_million",
                    "one_sided",
                ):
                    if row.get(key) not in (None, ""):
                        lines.append(_compact_text(f"{key}={row.get(key)}", 220))
                if row.get("snippet") not in (None, ""):
                    lines.append(_compact_text(f'snippet="{_normalise_example_text(row.get("snippet"))}"', 220))
                semantic_hit = _normalise_example_text(
                    row.get("kw") or row.get("text") or row.get("label")
                )
                if semantic_hit:
                    lines.append(_compact_text(f'hit="{semantic_hit}"', 220))
                kwic_line = _kwic_quote(index, row)
                if kwic_line:
                    lines.append(kwic_line)
                metric_line = _metric_quote(index, row)
                if metric_line:
                    lines.append(metric_line)
            else:
                lines.append(_compact_text(f"rows[{index}] {row}", 220))
    tables = raw_surface.get("tables")
    if isinstance(tables, dict):
        for table_name, entries in list(tables.items())[:6]:
            if isinstance(entries, list):
                # H11.8: der Resolver navigiert 'tables.<name>[i]' mit PUNKT
                # und ab 0. Die Anzeige schrieb 'table[<name>][i]' ab 1, also
                # falsche Klammer, falscher Singular, falsche Basis.
                for index, entry in enumerate(entries[:6], start=0):
                    pfad = f"tables.{table_name}"
                    if isinstance(entry, dict):
                        entry_line = _row_quote(pfad, index, entry)
                        if entry_line:
                            lines.append(entry_line)
                        kwic_line = _kwic_quote(index, entry)
                        if kwic_line:
                            lines.append(kwic_line)
                        metric_line = _metric_quote(index, entry)
                        if metric_line:
                            lines.append(metric_line)
                    else:
                        lines.append(_compact_text(f"{pfad}[{index}] {entry}", 220))
            else:
                lines.append(_compact_text(f"tables.{table_name} {entries}", 220))
    periods = raw_surface.get("periods")
    if isinstance(periods, list):
        from candyconc.candyconc_copilot.view_row_selection import ohne_pfad, zeilennummer

        for platz, period in enumerate(
            periods[:DEFAULT_GROUNDING_ROW_LIMIT],
            start=0,
        ):
            # A thinned series carries each period's path, it is the label.
            index, period = zeilennummer(period, platz, "periods"), ohne_pfad(period)
            if isinstance(period, dict):
                lines.append(_row_quote("periods", index, period))
            else:
                lines.append(_compact_text(f"periods[{index}] {period}", 220))
    warnings = raw_surface.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings[:8]:
            lines.append(_compact_text(f"warning={warning}", 220))
    relations = raw_surface.get("relations")
    if isinstance(relations, dict):
        for relation_name, metadata in list(relations.items())[:8]:
            lines.append(
                _compact_text(
                    f"relation[{relation_name}]={metadata}",
                    220,
                )
            )
    offsets = raw_surface.get("offsets")
    if isinstance(offsets, list):
        if offsets:
            lines.append(_compact_text(f"offsets={offsets}", 220))
    meta = raw_surface.get("meta")
    if isinstance(meta, dict):
        if meta.get("exactness") not in (None, ""):
            lines.append(_compact_text(f"exactness={meta.get('exactness')}", 220))
        candidate_generation = meta.get("candidateGeneration")
        if isinstance(candidate_generation, dict):
            for key in (
                "backend",
                "level",
                "method",
                "indexType",
                "searchMode",
                "requestedTopN",
                "candidateLimit",
                "candidateCount",
                "totalVectors",
                "lexicalSeedCount",
                "oversample",
            ):
                if candidate_generation.get(key) not in (None, ""):
                    lines.append(_compact_text(f"{key}={candidate_generation.get(key)}", 220))
        rerank = meta.get("rerank")
        if isinstance(rerank, dict):
            for key in ("enabled", "method", "inputCount", "outputCount"):
                if rerank.get(key) not in (None, ""):
                    lines.append(_compact_text(f"rerank.{key}={rerank.get(key)}", 220))
        filtering = meta.get("filtering")
        if isinstance(filtering, dict):
            for key in ("docsetApplied", "docsetDocCount", "minScore", "postFilterCandidateCount"):
                if filtering.get(key) not in (None, ""):
                    lines.append(_compact_text(f"filtering.{key}={filtering.get(key)}", 220))
    fallback = raw_surface.get("fallback")
    if isinstance(fallback, dict) and fallback:
        lines.append(_compact_text(f"fallback={fallback}", 220))
    diagnostics = raw_surface.get("diagnostics")
    if isinstance(diagnostics, dict):
        for key, value in list(diagnostics.items())[:DIAGNOSTIK_SICHTBAR]:
            lines.append(
                _compact_text(f"diagnostics.{key}={value}", 220)
            )
    clusters = raw_surface.get("clusters")
    if isinstance(clusters, list):
        for index, cluster in enumerate(clusters[:4], start=1):
            if isinstance(cluster, dict):
                lines.append(_compact_text(f"cluster[{index}] {cluster}", 220))
                for key in ("cluster_id", "size", "label"):
                    if cluster.get(key) not in (None, ""):
                        lines.append(_compact_text(f"{key}={cluster.get(key)}", 220))
                samples = ", ".join(_cluster_sample_values(cluster)[:4])
                if samples:
                    lines.append(_compact_text(f"samples={samples}", 220))
            else:
                lines.append(_compact_text(f"cluster[{index}] {cluster}", 220))
    plan = raw_surface.get("plan")
    if isinstance(plan, dict):
        lines.append(_compact_text(f"plan={plan}", 220))
    available_fields = raw_surface.get("available_fields")
    if isinstance(available_fields, list) and available_fields:
        lines.append(_compact_text(f"available_fields={available_fields}", 220))
    values = raw_surface.get("values")
    if isinstance(values, dict):
        value_counts = raw_surface.get("value_counts")
        if not isinstance(value_counts, dict):
            value_counts = {}
        for field, entries in list(values.items())[:12]:
            lines.append(_compact_text(f"field={field}", 220))
            if field in value_counts:
                lines.append(_compact_text(f"value_count[{field}]={value_counts[field]}", 220))
            # H11.8: der Resolver navigiert 'values.<feld>[i]' mit PUNKT.
            lines.append(_compact_text(f"values.{field}={entries}", 220))
    deduped: List[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line or line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def zaehlebene_und_nenner(attribut, sort_by) -> list[str]:
    """Describe the counting attribute and the selected logDice denominator.

    Word and lemma analyses use different counting levels. logdice and
    logdice_window also use different marginal totals. Render the selected
    level and definition already recorded in the evidence so readers can
    interpret the reported values on their actual basis.
    """

    heraus: list[str] = []
    ebene = _t({"word": "Wortform", "lemma": "Lemma"}, {"word": "word form", "lemma": "lemma"}).get(  # type: ignore[attr-defined]
        str(attribut or "").strip().lower()
    )
    if ebene:
        heraus.append(_t("Zählebene ", "count level ") + ebene)
    schluessel = str(sort_by or "").strip().lower()
    if schluessel == "logdice":
        heraus.append(_t("logDice über Korpusfrequenzen (Rychlý)", "logDice from corpus frequencies (Rychlý)"))
    elif schluessel == "logdice_window":
        heraus.append(_t("logDice über Fenstermaße (Distanztafel)", "logDice from window measures (distance table)"))
    return heraus


def dispersionsangaben(
    roh: Any,
    treffer: Any,
    dokumente: Any,
    lies: Any,
    zahl: Any,
) -> List[str]:
    """Describe dispersion using observed measures and their reference values.

    Report absence explicitly instead of interpreting placeholder zeros as
    measurements. With hits, keep observed measures alongside their computed
    reference range and document coverage. Partition sizes and hit counts
    affect the attainable DP range and its expected value.
    """

    try:
        n_treffer = int(float(treffer))
    except (TypeError, ValueError):
        n_treffer = -1
    try:
        n_dok = int(float(dokumente))
    except (TypeError, ValueError):
        n_dok = -1

    if n_treffer == 0:
        return [_t("Dispersion nicht berechenbar, 0 Treffer", "dispersion not computable, 0 hits")]

    masse: List[str] = []
    for etikett, schluessel in (
        ("DP", "dp"),
        ("DPnorm", "dpnorm"),
        ("Juilland-D", "juilland_d"),
        ("Carroll-D2", "carroll_d2"),
    ):
        wert = lies(schluessel, roh)
        if wert not in (None, ""):
            masse.append(f"{etikett} {zahl(wert)}")

    # Show the computed reference range when available.
    # Unequal partition sizes invalidate bounds derived for equal-sized parts.
    # Document coverage counts versions separately and does not by itself
    # establish the number of independent source texts.
    dp_erwartet = lies("dp_erwartet", roh)
    dp_min = lies("dp_min", roh)
    reichweite = lies("range", roh)
    if reichweite in (None, ""):
        reichweite = lies("nonzero_partitions", roh)
    spannen_satz = ""
    if dp_erwartet not in (None, "") and dp_min not in (None, ""):
        spannen_satz = _t(
            " Zu lesen ist DP gegen die Spanne, die diese Teilgrössen "
            "zulassen: erreichbare Untergrenze {}, bei "
            "zufälligem Streuen proportional zur Dokumentlänge "
            "{}, Obergrenze 1.",
            " DP is read against the range these part sizes allow: "
            "reachable lower bound {}, {} under random spread "
            "proportional to document length, upper bound 1.",
        ).format(zahl(dp_min), zahl(dp_erwartet))
    # Report missing document coverage explicitly.
    # When available, describe it as document coverage, including separate versions.
    reichweiten_satz = (
        _t(" Reichweite: {} von {} Dokumenten tragen Treffer.",
           " Range: {} of {} documents have hits.").format(zahl(reichweite), n_dok)
        if reichweite not in (None, "")
        else _t(" Die Reichweite liegt hier nicht vor.", " The range is not available here.")
    )

    try:
        erwartet_hoch = float(dp_erwartet) >= 0.8
    except (TypeError, ValueError):
        erwartet_hoch = False

    if erwartet_hoch:
        # Keep observed measures beside their expected values even when a fixed
        # cutoff would label the expected distribution as strongly clustered.
        # The profile itself uses dp_erwartet, so explain that reference without
        # discarding measured values or misdescribing the profile as a fixed-cutoff label.
        return list(masse) + [
            _t(
                "Dispersionsmaße bei {} Treffern auf {} "
                "Dokumente nur gegen die Spanne deutbar: bereits zufälliges "
                "Streuen ergibt hier DP {}, mehr als der feste "
                "Schnittpunkt 0,8, ab dem eine feste Leiter "
                "`strongly_clustered` vergäbe. Das Profil misst deshalb die Lage "
                "zu diesem Erwartungswert.",
                "Dispersion measures for {} hits on {} documents can only be "
                "read against the range: random spread alone gives DP {} "
                "here, more than the fixed cut point 0.8 from which a fixed "
                "scale would assign `strongly_clustered`. The profile "
                "therefore measures the position relative to this expected "
                "value.",
            ).format(n_treffer, n_dok, zahl(dp_erwartet))
            + (spannen_satz or "")
            + reichweiten_satz
        ]

    if not spannen_satz and 0 < n_treffer and 0 < n_dok and n_treffer * 10 < n_dok:
        # OHNE Referenzwerte bleibt die alte Zurueckhaltung richtig: eine
        # Zahl zwischen 0 und 1, deren erreichbare Untergrenze die Leserin
        # nicht kennt, liest sich als Befund und ist keiner. Die beiden
        # Saetze, die hier standen und eine Untergrenze nahe 1 behaupteten,
        # sind ersatzlos weg: sie galten nur fuer gleich grosse Teile.
        return [
            _t("Dispersionsmaße bei {} Treffern auf {} "
               "Dokumente ohne Referenzwerte nicht deutbar.",
               "Dispersion measures for {} hits on {} documents cannot be "
               "read without reference values.").format(n_treffer, n_dok)
            + reichweiten_satz
        ]
    # Include the reference range in the ordinary case as well.
    # A DP value alone cannot establish clustering relative to its expected value.
    if spannen_satz:
        masse = list(masse) + [spannen_satz.strip()]
    return masse
