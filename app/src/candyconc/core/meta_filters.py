from __future__ import annotations

import re
from typing import Any, Mapping

import numpy as np

# Die Normalisierung liegt jetzt im AST-Modul, damit der Parser sie
# erreicht. Sie hier zu wiederholen war der Grund, warum der
# where()-Eingang eine eigene, kuerzere Fassung bekam.
from cqlhpc.ast import MetaCond, MetaExpr, normalize_meta_value

from candyconc.i18n import lt


def pruefe_filterform(field: Any, raw: Any) -> None:
    """ONE form check for BOTH evaluators.

    The defect class: a filter has no effect and the call reports success.
    This check lists the admissible forms EXHAUSTIVELY instead of rejecting
    known bad forms one by one.

    Admissible is exactly:

    * a scalar (equality),
    * a non-empty list of SCALARS (multiple choice),
    * an op mapping ``{'op': <comparison>, 'value': ...}`` or
      ``{'op': 'between', 'lo': ..., 'hi': ...}``.

    Everything else raises. Three plausible looking forms and what they
    would do on a test index with 2,000 documents:

    * ``[{'op': '=', 'value': 'test'}]``: a recursion into the list finds
      'op' and approves the form. Both evaluators then turn it into an
      equality comparison against a dict: 0 of 683 documents,
      ``status: success``.
    * ``{'op': '='}`` without ``value``: comparison against None, the
      TypeError is caught in ``_meta_cmp``, 0 documents, success. And the
      evaluators disagree: the MetaIndex fast path raises, the document
      fallback stays silent.
    * ``[]`` or ``['']``: ``normalize_meta_value`` returns None, the filter
      disappears SILENTLY, and the answer is the UNFILTERED corpus with a
      success message: 2000 instead of 683 documents. That is more
      dangerous than 0, because a full count looks like a result and a zero
      stands out.

    NOT rejected are a SCALAR ``None`` or a whitespace-only string: by
    established contract that means "this field is not filtered", which is
    how the UI sends an empty input field, and
    ``test_meta_filters_golden.py:test_anchor5`` pins it. The difference is
    the INTENT: an omitted field is no filter, an empty selection list is
    one that can match nothing and still returns everything.
    """
    if isinstance(raw, Mapping):
        if "op" not in raw:
            raise _ungueltige_filterform(field, raw)
        op = str(raw["op"])
        if op == "between":
            _pruefe_skalar(field, raw.get("lo"))
            _pruefe_skalar(field, raw.get("hi"))
            if (normalize_meta_value(raw.get("lo")) is None
                    or normalize_meta_value(raw.get("hi")) is None):
                raise EingabeFormFehler(
                    lt(
                        "between-Filter fuer {field!r} braucht 'lo' und 'hi'",
                        "between filter for {field!r} needs 'lo' and 'hi'",
                    ).format(field=str(field))
                )
            return
        if op not in _VALID_META_OPS:
            raise EingabeFormFehler(_UNKNOWN_META_OPERATOR.format(op=op))
        _pruefe_skalar(field, raw.get("value"))
        # Nach der NORMALISIERUNG beurteilen, nicht davor: ein Wert aus
        # reinem Leerraum normalisiert zu None und vergleicht dann gegen
        # nichts, waehrend der Aufruf Erfolg meldet.
        if normalize_meta_value(raw.get("value")) is None:
            raise EingabeFormFehler(
                lt(
                    "Vergleichsfilter fuer {field!r} braucht 'value'. Ohne Wert "
                    "vergleicht der Filter gegen None und trifft nie etwas, "
                    "waehrend der Aufruf Erfolg meldet.",
                    "Comparison filter for {field!r} needs 'value'. Without a value "
                    "the filter compares against None and never matches anything, "
                    "while the call reports success.",
                ).format(field=str(field))
            )
        return
    if isinstance(raw, (list, tuple, set)):
        werte = list(raw)
        if not werte:
            raise EingabeFormFehler(
                lt(
                    "Leerer Werte-Filter fuer {field!r}. Ein leerer Filter faellt "
                    "still weg und liefert das UNGEFILTERTE Korpus mit "
                    "Erfolgsmeldung. Weglassen, wenn nicht gefiltert werden "
                    "soll.",
                    "Empty value filter for {field!r}. An empty filter is "
                    "silently dropped and returns the UNFILTERED corpus with a "
                    "success message. Leave it out if no filtering is "
                    "wanted.",
                ).format(field=str(field))
            )
        for element in werte:
            if isinstance(element, (Mapping, list, tuple, set)):
                raise _ungueltige_filterform(field, element) if isinstance(
                    element, Mapping
                ) else _fehler_verschachtelt(field)
            _pruefe_skalar(field, element)
        if normalize_meta_value(werte) is None:
            raise EingabeFormFehler(
                lt(
                    "Werte-Filter fuer {field!r} normalisiert zu nichts (nur leere "
                    "Zeichenketten). Er faellt still weg und liefert das "
                    "UNGEFILTERTE Korpus mit Erfolgsmeldung.",
                    "Value filter for {field!r} normalizes to nothing (only empty "
                    "strings). It is silently dropped and returns the "
                    "UNFILTERED corpus with a success message.",
                ).format(field=str(field))
            )
        return
    # Ein SKALARES None oder ein reiner Leerraum-String heisst nach
    # etabliertem Vertrag "dieses Feld ist nicht gefiltert" -- so schickt
    # die Oberflaeche ein nicht ausgefuelltes Feld, und
    # tests/core/test_meta_filters_golden.py:test_anchor5 pinnt es. Das
    # bleibt, und zwar bewusst: eine Vorfassung dieser Pruefung hat den
    # Anker gebrochen, um einen Befund ueber LEERE LISTEN zu schliessen.
    # Die leere Liste ist der gefaehrliche Fall (oben behandelt), der
    # ausgelassene Skalar ist der normale.
    _pruefe_skalar(field, raw)


def _fehler_verschachtelt(field: Any) -> "EingabeFormFehler":
    return EingabeFormFehler(
        lt(
            "Verschachtelte Liste im Filter fuer {field!r}. Eine Mehrfachauswahl "
            "ist eine flache Liste von Werten.",
            "Nested list in the filter for {field!r}. A multiple selection "
            "is a flat list of values.",
        ).format(field=str(field))
    )


def _pruefe_skalar(field: Any, wert: Any) -> None:
    """Ein Filterwert ist ein Skalar, keine Struktur."""
    if isinstance(wert, (bytes, bytearray)):
        raise EingabeFormFehler(
            lt(
                "Filterwert fuer {field!r} ist kein Text: {value!r}",
                "Filter value for {field!r} is not text: {value!r}",
            ).format(field=str(field), value=wert)
        )
    if isinstance(wert, (Mapping, list, tuple, set)):
        raise _ungueltige_filterform(field, wert) if isinstance(
            wert, Mapping
        ) else _fehler_verschachtelt(field)


def canonicalize_metadata_filters(
    metadata_filters: Mapping[str, Any] | None = None,
    *,
    date: str | None = None,
    genre: str | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metadata_filters:
        for key, value in metadata_filters.items():
            # CHECK first, THEN normalize. This function is a PRE-stage of
            # build_meta_expr/match_meta_filters and would otherwise make
            # their guard unreachable: ``normalize_meta_value`` returns None
            # for ``[]``, ``['']`` and ``[None]``, the
            # ``if normalized is not None`` DELETES the key, and the filter
            # is gone before anyone can object to it. metadata_values,
            # metadata_mask and document_search would then return the
            # UNFILTERED corpus with a success message: /analysis/meta_values
            # with {'split': []} would return ['test','train'],
            # byte-identical to the call WITHOUT a filter, while the sibling
            # route /analysis/meta_counts returns 400 for THE SAME input.
            #
            # Die legacy-Parameter ``date``/``genre`` behalten ihre
            # Bedeutung: None heisst dort "nicht uebergeben".
            pruefe_filterform(key, value)
            normalized = normalize_meta_value(value)
            if normalized is not None:
                merged[str(key)] = normalized
    if date is not None and "date" not in merged:
        normalized = normalize_meta_value(date)
        if normalized is not None:
            merged["date"] = normalized
    if genre is not None and "genre" not in merged:
        normalized = normalize_meta_value(genre)
        if normalized is not None:
            merged["genre"] = normalized
    return merged


# Legacy "transform" filter alias -> canonical "prompting_method" field + values.
# This is specific to the AI text pipeline and is the ONLY home for the translation. It is
# OPT-IN: invoke translate_meta_field_aliases() explicitly at the service entry points
# that historically accepted the legacy alias. It must NOT be baked into build_meta_expr
# / canonicalize_metadata_filters / metadata_mask / metadata_values, because the LLM
# document_search path passes free-form filters and a literal "transform" field must keep
# matching 0 docs there (it must not be silently rewritten).
TRANSFORM_VALUE_MAP: dict[str, str] = {
    "rewrite": "direct",
    "direct": "direct",
    "multistep": "prompt_builder",
    "multi_step": "prompt_builder",
    "prompt_builder": "prompt_builder",
    "summary": "zusammenfassung",
    "zusammenfassung": "zusammenfassung",
    "simple_corpus": "simple_corpus",
}


def translate_meta_field_aliases(filters: Mapping[str, Any]) -> dict[str, Any]:
    """Rename the legacy ``transform`` filter to ``prompting_method`` and map its
    value(s) through :data:`TRANSFORM_VALUE_MAP`. All other fields pass through
    unchanged. Unknown transform values pass through verbatim.

    Pure and opt-in — this is the single replacement for the four duplicated
    ``_canonicalize`` closures that previously lived in server.py/controller.py.
    """
    out: dict[str, Any] = {}
    for field, raw in filters.items():
        f = str(field)
        if f == "transform":
            if isinstance(raw, list):
                out["prompting_method"] = [TRANSFORM_VALUE_MAP.get(str(v), v) for v in raw]
            else:
                out["prompting_method"] = TRANSFORM_VALUE_MAP.get(str(raw), raw)
        else:
            out[f] = raw
    return out


# Comparison operators a range/date filter may use, mirroring the CQL engine's
# in-memory meta evaluator (cqlhpc/engine.py:_eval_meta_cond) so the per-doc
# fallback agrees with the meta_index fast path.
_VALID_META_OPS = frozenset({"=", "!=", ">=", "<=", ">", "<"})


class EingabeFormFehler(ValueError):
    """An invalid input form mapped to HTTP 400 by the shared application handler.

    Inherit ValueError so existing ``except (RuntimeError, ValueError)``
    handlers continue to catch this error. Central handling preserves the
    input diagnostic on routes without a local exception handler.
    """


_UNKNOWN_META_OPERATOR = lt(
    "Unbekannter Metadaten-Operator: {op!r}",
    "Unknown metadata operator: {op!r}",
)


def _is_op_filter(raw: Any) -> bool:
    """True if a filter value is the op-tagged shape {'op': ..., 'value'|'lo'/'hi': ...}."""
    return isinstance(raw, Mapping) and "op" in raw


def _meta_value_items(value: Any) -> list[Any]:
    normalized = normalize_meta_value(value)
    if normalized is None:
        return []
    if isinstance(normalized, list):
        return normalized
    return [normalized]


def _meta_value_matches(value: Any, target: Any) -> bool:
    """Equality across type boundaries.

    A filter value arrives as JSON or from a form field and is then often a
    string, while the document field holds a number. Comparing equal types
    only makes ``'1' == 1`` False, so ``=`` never matches and ``!=``
    matches EVERYTHING. On a 142M-token index, field ``step_index``:

        {'op':'!=','value':1}    19,272 documents   (correct)
        {'op':'!=','value':'1'}  250,535 documents  (the WHOLE corpus)

    Therefore the string form is compared as well. That is the tolerant
    direction: a filter that means something also matches it.
    """
    value_items = _meta_value_items(value)
    target_items = _meta_value_items(target)
    if not value_items or not target_items:
        return False
    for value_item in value_items:
        for target_item in target_items:
            if value_item == target_item:
                return True
            if str(value_item) == str(target_item):
                return True
    return False


class UnvergleichbarerFilter(EingabeFormFehler):
    """The filter value is not comparable with the field.

    If ``_meta_cmp`` caught every TypeError and returned False, the ``!=``
    branch would turn that False into True FOR EVERY DOCUMENT. On a
    142M-token index, where the field ``step_index`` is numeric:

        {'op':'!=','value':1}    19,272 documents   (correct)
        {'op':'!=','value':'1'}  250,535 documents  (the WHOLE corpus)

    On ``/analysis/meta_values`` the answer with the filter would be
    byte-identical to the answer WITHOUT it. The MetaIndex fast path rejects
    the same input loudly, the document fallback would stay silent: two
    evaluators, two meanings.

    The fast path also rejects ordering comparisons on string fields ('Meta
    Index: Stringvergleich nur mit = oder !='), while Python compares
    lexicographically. Because ``build_meta_expr`` splits the between branch
    into >= and <=, that affects the WHOLE between branch, exactly the date
    range shape the op form exists for.
    """


def _meta_cmp(value: Any, op: str, target: Any) -> bool:
    """Ein Vergleich, der bei Unvergleichbarkeit WIRFT statt zu schweigen.

    Die Gleichheitszweige bleiben tolerant: ``=`` und ``!=`` sind ueber
    ``_meta_value_matches`` fuer jede Wertkombination definiert (kein
    Treffer heisst kein Treffer). Nur die ORDNUNGSvergleiche koennen
    unvergleichbar sein, und dort ist Schweigen die Falle.
    """
    if op == "=":
        return _meta_value_matches(value, target)
    if op == "!=":
        return not _meta_value_matches(value, target)
    if op not in (">=", "<=", ">", "<"):
        return False
    if value is None:
        # Feld fehlt im Dokument: eine Ordnungsaussage ist dann nicht
        # falsch, sondern gegenstandslos. Das Dokument faellt heraus,
        # ohne dass die ganze Anfrage scheitert.
        return False
    # Ordering comparisons on string fields are allowed, although the
    # MetaIndex only compares strings with = or !=. ISO date ranges ARE
    # strings, and {'op':'between','lo':'2014-01-01',...} on date is exactly
    # the shape the op form exists for. Lexicographic comparison is correct
    # there.
    #
    # The divergence is therefore OPEN: the MetaIndex is stricter than
    # necessary here. Closing it from the other side (the index learns
    # lexicographic order) is an engine change and not done.
    # tests/core/test_meta_filters.py records it as xfail.
    try:
        if op == ">=":
            return value >= target
        if op == "<=":
            return value <= target
        if op == ">":
            return value > target
        return value < target
    except TypeError:
        # Gold anchor 13 pins "incomparable str vs number -> no match,
        # never raises". A single document with year="n/a" must not break
        # the whole query.
        #
        # This False cannot turn into "matches everything" under !=, because
        # _meta_value_matches compares type-tolerantly: '1' and 1 mean the
        # same, so != never reaches the inversion. On an index of 250,535
        # documents {'op':'!=','value':'1'} returns the same set as the
        # integer form, not all 250,535 documents.
        return False


def _ungueltige_filterform(field: Any, raw: Any) -> ValueError:
    """A mapping WITHOUT 'op' is not a valid filter form.

    Unchecked, it would fall through in BOTH evaluators to
    ``normalize_meta_value``, which returns mappings unchanged, and become an
    EQUALITY COMPARISON AGAINST A DICT, which never matches. A filter
    ``{'gte': ..., 'lte': ...}`` on ``date`` then yields docsets with 0
    documents and 0 tokens while ``create_docset`` reports
    ``status: success``, and every downstream count is 0 with reported
    success: an operation that does nothing and reports success.

    Both evaluators must reject it. ``match_meta_filters`` serves the
    document metadata fallback of ``metadata_mask``, ``metadata_values``,
    ``_search_docset_doc_ids`` and ``routes/analysis.py``, and
    ``create_docset`` WITH a query runs through ``_search_docset_doc_ids``.
    A check in ``build_meta_expr`` alone would only cover ``create_docset``
    WITHOUT a query.
    """
    return EingabeFormFehler(
        lt(
            "Ungueltiger Metadaten-Filter fuer {field!r}: {raw!r}. Bereiche werden "
            "als {{'op': 'between', 'lo': ..., 'hi': ...}} geschrieben, "
            "Vergleiche als {{'op': '>=', 'value': ...}}. Gueltige "
            "Operatoren: {ops}.",
            "Invalid metadata filter for {field!r}: {raw!r}. Ranges are "
            "written as {{'op': 'between', 'lo': ..., 'hi': ...}}, "
            "comparisons as {{'op': '>=', 'value': ...}}. Valid "
            "operators: {ops}.",
        ).format(
            field=str(field),
            raw=dict(raw) if isinstance(raw, Mapping) else raw,
            ops=", ".join(sorted(_VALID_META_OPS)),
        )
    )


def match_meta_filters(meta: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    for field, raw in filters.items():
        pruefe_filterform(field, raw)
        if _is_op_filter(raw):
            meta_value = meta.get(str(field))
            op = str(raw["op"])
            if op == "between":
                if not (_meta_cmp(meta_value, ">=", raw.get("lo")) and _meta_cmp(meta_value, "<=", raw.get("hi"))):
                    return False
            elif not _meta_cmp(meta_value, op, raw.get("value")):
                return False
            continue
        value = normalize_meta_value(raw)
        if value is None:
            continue
        meta_value = meta.get(str(field))
        if not _meta_value_matches(meta_value, value):
            return False
    return True


def build_meta_expr(filters: Mapping[str, Any]) -> MetaExpr | None:
    parts: list[MetaExpr] = []
    for field, raw in filters.items():
        # Use the same input validation as match_meta_filters so both evaluators
        # accept and reject the same filter forms.
        pruefe_filterform(field, raw)
        # Range/date op-tagged shape {'op': '>=', 'value': X} or {'op':'between','lo','hi'}.
        # Handled BEFORE normalize (which would strip a dict). Additive: equality inputs
        # are untouched, so existing MetaExpr output is byte-identical.
        if _is_op_filter(raw):
            op = str(raw["op"])
            if op == "between":
                # THE SAME normalization as in the document fallback, which
                # always applies it via _meta_cmp -> _meta_value_matches ->
                # _meta_value_items -> normalize_meta_value. Passing the
                # value LITERALLY on this fast path would give a filter
                # whose meaning depends on the path as soon as the value
                # contains a space: {'op':'=','value':'test '} would return
                # 0 against 683 on a test index with 2,000 documents, and
                # {'op':'!=','value':' test '} 2000 of 2000 there and 250,535
                # of 250,535 on a 142M-token corpus, the WHOLE corpus with
                # status success.
                lo = normalize_meta_value(raw.get("lo"))
                hi = normalize_meta_value(raw.get("hi"))
                if lo is None or hi is None:
                    raise EingabeFormFehler(lt(
                        "between-Filter braucht 'lo' und 'hi'",
                        "between filter needs 'lo' and 'hi'",
                    ))
                parts.append(MetaExpr(kind="and", parts=(
                    MetaExpr(kind="cond", parts=(MetaCond(field=str(field), op=">=", value=lo),)),
                    MetaExpr(kind="cond", parts=(MetaCond(field=str(field), op="<=", value=hi),)),
                )))
                continue
            if op not in _VALID_META_OPS:
                raise EingabeFormFehler(_UNKNOWN_META_OPERATOR.format(op=op))
            # Siehe oben: derselbe Wert muss auf beiden Auswertern
            # dasselbe bedeuten.
            wert = normalize_meta_value(raw.get("value"))
            if wert is None:
                raise EingabeFormFehler(
                    lt(
                        "Vergleichsfilter fuer {field!r} braucht 'value'.",
                        "Comparison filter for {field!r} needs 'value'.",
                    ).format(field=str(field))
                )
            parts.append(MetaExpr(kind="cond", parts=(MetaCond(field=str(field), op=op, value=wert),)))
            continue
        value = normalize_meta_value(raw)
        if value is None:
            continue
        if isinstance(value, list):
            conds = [MetaCond(field=str(field), op="=", value=item) for item in value]
            if not conds:
                continue
            if len(conds) == 1:
                parts.append(MetaExpr(kind="cond", parts=(conds[0],)))
            else:
                parts.append(
                    MetaExpr(
                        kind="or",
                        parts=tuple(MetaExpr(kind="cond", parts=(cond,)) for cond in conds),
                    )
                )
        else:
            parts.append(MetaExpr(kind="cond", parts=(MetaCond(field=str(field), op="=", value=value),)))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MetaExpr(kind="and", parts=tuple(parts))


def _doc_metadata(fast_index: Any) -> Any:
    """``doc_metadata``, auch wenn eine Huelle uebergeben wurde.

    Siehe die Begruendung in :func:`metadata_fields`. Beide Zugriffe
    haben dieselbe Ursache und werden deshalb gleich behandelt.
    """

    gesehen: set[int] = set()
    knoten = fast_index
    while knoten is not None and id(knoten) not in gesehen:
        gesehen.add(id(knoten))
        doc_metadata = getattr(knoten, "doc_metadata", None)
        if doc_metadata is not None:
            return doc_metadata
        knoten = getattr(knoten, "fast_index", None)
    return None


#: The field names present in the DOCUMENTS, scanned once per index.
#:
#: Without the cache every rejected call scans all documents. On a corpus of
#: 479,000 documents that costs 4.19 seconds per call, the difference between
#: a clear error message and an interface that appears to hang.
_DOKUMENTFELDER_CACHE: dict[int, frozenset[str]] = {}


def clear_document_fields_cache() -> None:
    """Forget the field sets (keyed by object id, which a reopened index can reuse)."""
    _DOKUMENTFELDER_CACHE.clear()


def _dokumentfelder(fast_index: Any) -> frozenset[str] | None:
    """Alle Feldnamen aus den Dokument-Metadaten, einmal je Index."""

    doc_metadata = _doc_metadata(fast_index)
    if doc_metadata is None:
        return None
    schluessel = id(doc_metadata)
    gemerkt = _DOKUMENTFELDER_CACHE.get(schluessel)
    if gemerkt is not None:
        return gemerkt
    gesehen: set[str] = set()
    for meta in doc_metadata.values():
        if isinstance(meta, Mapping):
            gesehen.update(str(key) for key in meta.keys())
    gefroren = frozenset(gesehen)
    _DOKUMENTFELDER_CACHE[schluessel] = gefroren
    return gefroren


def metadata_fields(fast_index: Any) -> list[str]:
    """The metadata fields of the corpus, whichever wrapper is passed in.

    ``CorpusIndex`` is a WRAPPER. ``meta_index`` and ``doc_metadata`` sit on
    the inner ``fast_index``, and ``CorpusIndex.metadata_fields`` forwards
    exactly that. Without the descent below, passing the wrapper returns an
    empty list, for example on a parliamentary corpus index:

        CorpusIndex.metadata_fields()   -> ['protocol_lp', 'protocol_year',
                                            'speaker_parlgroup',
                                            'speaker_party', 'speaker_role']
        meta_filters.metadata_fields()  -> []

    For ``unbekannte_felder`` an empty list does not mean "unknown" but "no
    field is unknown". The guard would then be COMPLETELY ineffective on
    every call path that passes the wrapper, and an unknown field returns 0
    documents or the WHOLE corpus depending on the operator. ``{'party':
    'AfD'}`` and even the typo ``{'speaker_partei': 'AfD'}`` would count as
    known fields.
    """

    meta_index = getattr(fast_index, "meta_index", None)
    fields = getattr(meta_index, "fields", None)
    if isinstance(fields, dict) and fields:
        return sorted(str(name) for name in fields.keys())

    doc_metadata = getattr(fast_index, "doc_metadata", None)
    if doc_metadata is not None:
        out: set[str] = set()
        for meta in doc_metadata.values():
            if isinstance(meta, Mapping):
                out.update(str(key) for key in meta.keys())
        if out:
            return sorted(out)

    # Eine Ebene tiefer, falls eine Huelle uebergeben wurde. Der Vergleich
    # auf Identitaet verhindert eine Endlosschleife, falls ein Objekt sich
    # selbst als ``fast_index`` fuehrt.
    inner = getattr(fast_index, "fast_index", None)
    if inner is not None and inner is not fast_index:
        return metadata_fields(inner)
    return []


def pruefe_filter_traegt_bedingung(
    filters: Mapping[str, Any] | None,
    *,
    fast_index: Any = None,
) -> None:
    """Wirft, wenn ein NICHT leerer Filter zu keiner Bedingung normalisiert.

    NO filter means the whole corpus. A filter that normalizes to nothing
    does NOT mean that: the caller meant a restriction and would get
    everything, with a success message. On a test index with 2,000
    documents::

        {}                  2000   correct
        {"split": "test"}    683
        {"split": "   "}    2000   the whole corpus
        {"split": ""}       2000

    The LIST forms of the same input already raise in
    ``_pruefe_filterform``. This check covers the SCALAR shape and sits
    here so that all seams call the same code. A check only in
    ``server._doc_ids_from_meta`` would leave ``/analysis/meta_counts``
    returning the full distribution for ``{"split": ""}``, byte-identical
    to the call without any filter.

    The golden anchor ``test_anchor5`` stays untouched: it states that
    ``build_meta_expr`` builds ``None`` for whitespace. This check sits
    above the build, not inside it.

    PER FIELD, not on the whole dict. Asking
    ``build_meta_expr(filters) is not None``, i.e. whether ANY field yields
    a condition, would let a single effective neighbouring field switch the
    check off, and that is exactly what every real UI sends. On the same
    test index such a check would give::

        {"split": "test", "source": "tweets"}   683
        {"split": "",     "source": "tweets"}  2000   split is dropped
        {"split": "   ",  "source": "tweets"}  2000
        {"split": None,   "source": "tweets"}  2000

    The 2000 are byte-identical to the call without ``split``. The sibling
    guard ``unbekannte_felder`` uses the same granularity: it checks field
    by field.
    """
    if not filters:
        return
    # Nur BEKANNTE Felder. Ein unbekanntes Feld kann nie still das ganze
    # Korpus liefern -- dafuer sorgt ``unbekannte_felder``, das in JEDE
    # Richtung auf die leere Menge geht. Ein bekanntes Feld ohne Wert kann
    # es sehr wohl, und nur das ist der Fall dieser Pruefung. Ohne diese
    # Trennung uebernahm der Formfehler den Vortritt vor dem bestehenden
    # Vertrag "ein unbekanntes Feld trifft nichts, egal was danebensteht",
    # den tests/backend/test_gate6_class_findings.py TestC und TestM
    # pinnen. Diese korrekten Tests bleiben unangetastet.
    unbekannt = set(unbekannte_felder(fast_index, filters)) if fast_index is not None else set()
    ohne_bedingung = [
        str(feld) for feld, wert in dict(filters).items()
        if str(feld) not in unbekannt and build_meta_expr({feld: wert}) is None
    ]
    if not ohne_bedingung:
        return
    raise EingabeFormFehler(
        lt(
            "Der Filter {filters} normalisiert zu keiner Bedingung. Ein Feld ohne "
            "Wert faellt still weg und liefert die UNGEFILTERTE Menge mit "
            "Erfolgsmeldung. Entweder Werte angeben oder das Feld weglassen.",
            "The filter {filters} normalizes to no condition. A field without "
            "a value is silently dropped and returns the UNFILTERED set with a "
            "success message. Either give values or leave out the field.",
        ).format(filters=repr({f: dict(filters)[f] for f in ohne_bedingung}))
    )


def unbekannte_felder(fast_index: Any, filters: Mapping[str, Any]) -> list[str]:
    """The filter fields that do not exist in the corpus.

    The document fallback sees one document at a time and does not know the
    corpus FIELD SET that the MetaIndex knows. Unchecked, it answers an
    unknown field DEPENDING ON THE DIRECTION:

        {'gibtsnicht': 'x'}                      0 documents
        {'gibtsnicht': {'op':'!=','value':'x'}}  ALL documents

    The second shape is the defect. ``_meta_value_matches`` returns False
    for a missing field, and the ``!=`` branch turns that into True for
    EVERY document: 741 instead of 0 on a small test index, 162,694
    documents and 120,541,515 tokens on a 142M-token corpus, each
    byte-identical to the control WITHOUT a filter. A full count looks like
    a result, a zero stands out.

    The direction is EMPTY, not an error: ``test_docset_from_search_zero_
    filter_keeps_counts_consistent`` pins that a filter on a missing field
    returns an empty docset with HTTP 200. Raising here would break that
    contract and 22 correct tests. An unknown field matches nothing, in
    EVERY direction.

    Returns the list of unknown fields so that the caller decides: the seam
    that holds the corpus short-circuits to empty.
    """
    if not filters:
        return []
    bekannt = set(metadata_fields(fast_index) or ())
    if not bekannt:
        return []
    kandidaten = [str(f) for f in filters if str(f) not in bekannt]
    if not kandidaten:
        return []
    # metadata_fields meldet die Feldmenge des META-INDEX, und die ist
    # KLEINER als das, was die Dokumente tragen. Am 142M-Korpus gemessen:
    # gemeldet 15 Felder, in den Dokumenten 23. Die acht Differenzfelder
    # sind gueltig, darunter 'genre' (ein legacy-Parameter DIESES Moduls),
    # 'doc_id' und 'path'. Eine Vorfassung hat sie als unbekannt
    # abgewiesen -- eine Reparatur, die gueltige Filter bricht, ist
    # schlimmer als der Defekt, den sie schliesst.
    #
    # Deshalb wird gegen die Dokument-Metadaten GEGENGEPRUEFT, bevor ein
    # Feld als unbekannt gilt. Der Scan laeuft nur fuer die Kandidaten,
    # also nur, wenn der Index-Feldname fehlt, und bricht beim ersten
    # Fund ab.
    # Auch hier die Huelle aufloesen. ``doc_metadata`` sitzt wie
    # ``meta_index`` auf dem INNEREN fast_index, und ohne diesen Griff
    # war die Gegenpruefung auf jedem Aufrufpfad, der die Huelle reicht,
    # ein ``return []``, also "kein Feld ist unbekannt". Die Wache fiel
    # damit ZWEIMAL nach offen, und zwar still.
    dokumentfelder = _dokumentfelder(fast_index)
    if dokumentfelder is None:
        return []
    return sorted(set(kandidaten) - dokumentfelder)


def unbekannte_werte(
    fast_index: Any,
    filters: Mapping[str, Any],
) -> list[tuple[str, Any, list[str]]]:
    """Gleichheitsfilter, deren Wert das Feld nicht kennt: (feld, wert, vorhanden).

    Example: ``{'model': 'ai'}`` on a corpus whose ``model`` field holds
    generator names and ``human`` but no value "ai". Unchecked, the call
    reports success with 0 documents, and the model computes against an
    EMPTY comparison side and reads a finding into it. A value outside the
    inventory matches nothing, in the same direction as an unknown FIELD,
    which ``unbekannte_felder`` rejects.

    Vertrag wie die Engine selbst (``_meta_value_matches``): Gleichheit
    ueber Typgrenzen, also auch die ``str``-Form. Range-Filter
    (op/between-Dikte) haben keinen Wertvorrat und werden nicht geprüft.
    Ein Feld ohne jeden Wert am Index bleibt unbehelligt: das ist "weiss
    ich nicht", nicht "wert ist falsch".
    """
    if not filters:
        return []
    meta = _doc_metadata(fast_index)
    if meta is None:
        return []
    inventare: dict[str, tuple[set, set] | None] = {}

    def inventar(feld: str) -> tuple[set, set] | None:
        if feld not in inventare:
            roh: set = set()
            formen: set = set()
            for eintrag in meta.values():
                if not isinstance(eintrag, Mapping) or feld not in eintrag:
                    continue
                wert = eintrag[feld]
                if isinstance(wert, (list, tuple, set)):
                    for teil in wert:
                        roh.add(teil)
                        formen.add(str(teil))
                elif wert is not None:
                    roh.add(wert)
                    formen.add(str(wert))
            # Ein Feld mit RIESIGEM Wertvorrat (doc_id, Pfad, Freitext) ist
            # keine kategoriale Achse: dort ist ein fehlender Wert kein
            # Beweis, und die Liste der "vorhandenen Werte" waere keine
            # Hilfe. Getroffen werden sollen genau die Achsen des
            # Lauf-3-Befunds (model, split, text_type): kleine Inventare.
            inventare[feld] = (roh, formen) if len(formen) <= 64 else None
        return inventare[feld]

    befunde: list[tuple[str, Any, list[str]]] = []
    for feld, wert in filters.items():
        kandidaten = (
            list(wert) if isinstance(wert, (list, tuple, set)) else [wert]
        )
        for kandidat in kandidaten:
            if kandidat is None or isinstance(kandidat, (dict, list, tuple, set)):
                continue
            # Leerwerte (leer, Leerraum) sind eine EIGENE Klasse mit
            # gepinnter Behandlung an jeder Naht (gate6, TestU): sie
            # gehoert dieser Wache nicht.
            if isinstance(kandidat, str) and not kandidat.strip():
                continue
            inventar_feld = inventar(str(feld))
            if inventar_feld is None:
                continue
            roh, formen = inventar_feld
            if not roh and not formen:
                continue
            if kandidat in roh or str(kandidat) in formen:
                continue
            befunde.append(
                (str(feld), kandidat, sorted(formen)[:12]))
    return befunde


def metadata_values(
    fast_index: Any,
    field: str,
    *,
    filters: Mapping[str, Any] | None = None,
    limit: int | None = None,
) -> list[str]:
    """Return distinct metadata values, optionally stopping after ``limit``.

    Value pickers are suggestions, not a complete research result. A bounded
    request must therefore stop while scanning instead of first materialising a
    document-identity-sized value set in Python.
    """
    # Unwrap the index before looking up metadata values. Reading the wrapper
    # directly can hide values that exist on its inner index.
    doc_metadata = _doc_metadata(fast_index)
    if doc_metadata is None:
        return []
    if limit is not None:
        limit = max(0, int(limit))
        if limit == 0:
            return []
    # FUENFTE Naht, siehe metadata_mask. Auf den ROHEN Filtern.
    pruefe_filter_traegt_bedingung(filters, fast_index=fast_index)
    normalized_filters = canonicalize_metadata_filters(filters)
    # Dieselbe Feldpruefung wie in metadata_mask: diese Funktion nutzt den
    # Doc-Rueckfall DIREKT und hat deshalb auf ein unbekanntes Feld
    # geantwortet, wo der MetaIndex abweist -- {'gibtsnicht':'x'} lieferte
    # [], {'split':{'op':'!=','value':1}} lieferte den VOLLEN Wertesatz,
    # also dasselbe wie ohne Filter, mit Erfolgsmeldung.
    # Die ROHEN Schluessel, nicht die normalisierten. Das Normalisieren
    # laesst Eintraege FALLEN, deren Wert zu nichts wird, und ein
    # unbekanntes Feld verschwand dadurch aus der Pruefung:
    # {'gibtsnicht': '   '} war an dieser Naht unauffaellig und an den
    # beiden Naehten in server.py und routes/analysis.py, die den rohen
    # Dikt lesen, ein Befund. Ein Feld ist unbekannt, unabhaengig davon,
    # was danebensteht.
    if unbekannte_felder(fast_index, filters or {}):
        return []
    values: set[str] = set()
    for meta in doc_metadata.values():
        if not isinstance(meta, Mapping):
            continue
        if normalized_filters and not match_meta_filters(meta, normalized_filters):
            continue
        value = meta.get(field)
        normalized = normalize_meta_value(value)
        if isinstance(normalized, list):
            for item in normalized:
                values.add(str(item))
                if limit is not None and len(values) >= limit:
                    return sorted(values)[:limit]
        elif normalized is not None:
            values.add(str(normalized))
            if limit is not None and len(values) >= limit:
                return sorted(values)[:limit]
    return sorted(values)


#: ``where`` als Aufruf, nicht als Teil eines Wortes oder Wertes.
_WHERE_AUFRUF = re.compile(r"\bwhere\s*\(", re.IGNORECASE)


def where_dokumente(idx: Any, query: Any) -> Any:
    """Die Dokumente, auf die eine ``where()``-Abfrage sich einschraenkt.

    Liegt HIER und nicht im Copilot-Werkzeugmodul, weil BEIDE Nahtstellen
    ihn brauchen. Eine Vorfassung sass nur an der Copilot-Naht, und die
    REST-Route /analysis/collocates meldete fuer dieselbe Abfrage weiter
    den Erwartungswert gegen den ganzen Korpus (0,57 statt 1,1), ein
    Referenzuniversum von 56.191 statt 18.761 Tokens und gar keinen
    Scope. Ein Fix an einer von zwei Nahtstellen ist eine Verschiebung,
    und die Commit-Nachricht dazu hat die Klasse als geschlossen
    gemeldet.

    ``None`` heisst "keine Einschraenkung im Abfragetext". Laesst sich eine
    vorhandene Bedingung nicht aufloesen, wirft der Auswerter, und der
    Aufruf scheitert sichtbar, statt still den Korpusnenner zu nehmen.
    """
    from candyconc.core.cql_macros import normalize_query_input

    roh = normalize_query_input(str(query or "").strip())
    if not roh.lower().startswith("cql:"):
        return None
    ausdruck = roh[4:].strip()
    # Wortgrenze plus oeffnende Klammer, nicht blosse Teilzeichenkette. Die
    # Vorfassung pruefte `"where" in ausdruck.lower()`, und damit zog ein
    # Lemma wie `[lemma="wherever"` den ganzen Parser-Vorlauf an sich. Wo der
    # Aufrufer den Parse-Fehler nicht klassifiziert, wurde aus einem 400 ein
    # 500 -- gemessen an run_cqlf_query fuer `cql:[lemma="wherever"`.
    if not _WHERE_AUFRUF.search(ausdruck):
        return None
    from cqlhpc.ast import Where
    from cqlhpc.parser import parse_cql

    # An JEDER Stelle des Baums, nicht nur an der Wurzel. Eine Vorfassung
    # sah nur ein Where ganz aussen, und
    #     within(<s>, where(split="test", [word="und"]))
    # zaehlte 262 Treffer gegen den Nenner des GANZEN Korpus (56.191)
    # statt gegen 18.761. Genau die Verwechslung, gegen die der Punkt
    # gebaut ist, eine Klammer weiter innen.
    meta = getattr(idx.fast_index, "meta_index", None)
    if meta is None:
        return None
    gefunden: list[Any] = []
    stapel = [parse_cql(ausdruck)]
    while stapel:
        knoten = stapel.pop()
        if isinstance(knoten, Where):
            gefunden.append(knoten.expr)
        for name in ("node", "inner", "child", "body", "parts", "items"):
            wert = getattr(knoten, name, None)
            if isinstance(wert, (list, tuple)):
                stapel.extend(wert)
            elif wert is not None:
                stapel.append(wert)
    if not gefunden:
        return None
    maske = None
    for ausdruck_knoten in gefunden:
        m = np.asarray(meta.mask_for_expr(ausdruck_knoten))
        maske = m if maske is None else (maske & m)
    return np.nonzero(maske)[0].astype(np.uint32, copy=False)


def metadata_mask(
    fast_index: Any,
    filters: Mapping[str, Any],
    *,
    doc_count: int,
) -> np.ndarray | None:
    # Order: FORM, then field, then short circuit.
    # canonicalize_metadata_filters performs the form check. A field check
    # placed before it would swallow it: a malformed condition on an unknown
    # field would come back as an empty mask instead of an input error.
    # The guard is required here because ``if not normalized: return None``
    # means "no filter", i.e. the whole corpus, to the caller. Without it
    # ``{"split": ""}`` returns None here, while the sibling route
    # ``/analysis/meta_counts`` raises 400 for the same input. That affects
    # ``/analysis/meta_values``, ``metadata_values_tool`` and
    # ``document_search_tool``: the copilot's evidence supplier would return
    # documents from ``train`` while the model believes it filtered for
    # ``test``.
    #
    # Auf den ROHEN Filtern, vor der Alias-Uebersetzung, damit die Meldung
    # das Feld nennt, das die Aufruferin geschickt hat.
    pruefe_filter_traegt_bedingung(filters, fast_index=fast_index)
    normalized = canonicalize_metadata_filters(filters)
    # Die ROHEN Schluessel, und VOR dem Kurzschluss auf None. ``None``
    # heisst beim Aufrufer "kein Filter", also ganzes Korpus, und ein
    # Filter auf ein unbekanntes Feld normalisiert oft zu nichts:
    # {'gibtsnichtxyz': '   '} kam so am Waechter vorbei.
    if unbekannte_felder(fast_index, filters or {}):
        return np.zeros(int(doc_count), dtype=np.uint8)
    if not normalized:
        return None

    # VOR dem MetaIndex-Zweig. Eine Vorfassung stand HINTER dessen
    # Rueckgabepunkt, also nur im Doc-Rueckfall -- und jeder real gebaute
    # Index hat einen MetaIndex. Sie war damit auf beiden vorhandenen
    # Korpora toter Code, waehrend Docstring und Commit-Nachricht
    # behaupteten, sie sitze an dieser Naht.

    meta_index = getattr(fast_index, "meta_index", None)
    if meta_index is not None:
        expr = build_meta_expr(normalized)
        if expr is None:
            return None
        try:
            mask = meta_index.mask_for_expr(expr).astype(np.uint8, copy=False)
        except Exception as exc:
            raise RuntimeError(lt(
                "MetaIndex-Filter fehlgeschlagen; breche ab statt still auf "
                "Doc-Metadata-Fallback zu wechseln.",
                "Metadata index filter failed. Stopping instead of silently "
                "switching to the document metadata fallback.",
            )) from exc
        if int(mask.shape[0]) != int(doc_count):
            raise RuntimeError(
                "MetaIndex-Filter lieferte eine Maske mit falscher Dokumentzahl "
                f"({int(mask.shape[0])} statt {int(doc_count)})."
            )
        return mask

    # Der Doc-Rueckfall sieht ein Dokument nach dem anderen und kennt die
    # FELDMENGE des Korpus nicht, die der MetaIndex kennt. Er hat deshalb
    # auf ein unbekanntes Feld geantwortet, wo der Index abweist:
    # {'gibtsnicht': 'x'} lieferte 0, {'gibtsnicht': {'op':'!=','value':'x'}}
    # lieferte 2000 von 2000 -- das ganze Korpus, mit Erfolgsmeldung.
    #
    # Diese Naht hat beides: den Korpus und den Rueckfall. Hier wird die
    # Feldmenge deshalb geprueft, bevor gezaehlt wird.
    mask = np.zeros(int(doc_count), dtype=np.uint8)
    for doc_idx in range(int(doc_count)):
        meta = fast_index._doc_meta_for_idx(int(doc_idx))
        if isinstance(meta, Mapping) and match_meta_filters(meta, normalized):
            mask[int(doc_idx)] = 1
    return mask


__all__ = [
    "unbekannte_felder",
    "where_dokumente",
    "build_meta_expr",
    "canonicalize_metadata_filters",
    "match_meta_filters",
    "metadata_fields",
    "metadata_mask",
    "metadata_values",
    "normalize_meta_value",
    "translate_meta_field_aliases",
    "TRANSFORM_VALUE_MAP",
]
