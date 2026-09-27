from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple, Callable
import json
import os
import re
import sre_parse

import numpy as np

from .ast import Cond, TokenClause
try:
    from candyconc.core.fast_index_native import lexicon_match_regex, lexicon_match_regex_ids
except Exception:  # pragma: no cover - clean wheels may omit native extension
    lexicon_match_regex = None
    lexicon_match_regex_ids = None

try:
    from .cython._lexicon import lookup_id as _cy_lex_lookup_id  # type: ignore
    from .cython._lexicon import lookup_ids as _cy_lex_lookup_ids  # type: ignore
except Exception:  # pragma: no cover
    _cy_lex_lookup_id = None
    _cy_lex_lookup_ids = None
from .corpus import Corpus
from .errors import UNKNOWN_ATTRIBUTE, UNRESOLVABLE, UnresolvableConditionError, lt


@dataclass(frozen=True, slots=True)
class Indexable:
    """A postings-generating condition."""

    attr: str
    type_ids: np.ndarray  # int32
    est_len: int          # estimated merged postings length


@dataclass(frozen=True, slots=True)
class CompiledClause:
    """A token clause compiled to integer-ID checks.

    We keep the structure small and predictable so it can be lowered
    into Cython-friendly arrays for the NFA runner.
    """

    # conditions: list of (attr_index, op_code, values_int32)
    # attr_index mapping: 0=lemma,1=pos,2=word, -1=other (python fallback)
    conds: Tuple[Tuple[str, str, np.ndarray], ...]

    def match_at(self, corpus: Corpus, pos: int) -> bool:
        for attr, op, vals in self.conds:
            tv = int(corpus.attr(attr)[pos])
            if op == '=':
                if tv != int(vals[0]):
                    return False
            elif op == '!=':
                if tv == int(vals[0]):
                    return False
            elif op == 'in':
                if not _contains(vals, tv):
                    return False
            else:
                # unsupported op in fast matcher
                return False
        return True


# A token id no real lexicon entry can hold. Used as a "never matches" sentinel
# for out-of-vocabulary literal conditions so the NFA runner can still compile a
# valid (but unsatisfiable) predicate instead of the compile step aborting. The
# matcher reads ``values[off]`` for the ``=`` op, so the array must be non-empty.
_NEVER_MATCH_IDS = np.asarray([-1], dtype=np.int32)

# Classified as a caller error (HTTP 400) in services/backend/query_count.py.
_NEGATED_REGEX_MESSAGE = lt(
    "Regex mit '!=' (z.B. [word!=\"Leut.*\"]) wird noch nicht "
    "unterstützt. Bitte ein positives Regex-Muster (= oder ~) "
    "verwenden.",
    "Regex with '!=' (e.g. [word!=\"free.*\"]) is not supported "
    "yet. Use a positive regex pattern (= or ~).",
)


def compile_clause(
    clause: TokenClause, corpus: Corpus, *, progress_cb: Callable | None = None
) -> CompiledClause:
    """Lower a token clause to integer-ID checks for the NFA runner.

    Out-of-vocabulary literal conditions (``=``/``in``/``~`` that resolve to no
    lexicon id) compile to a *never-matching sentinel* predicate (``attr = -1``)
    rather than raising. This is what lets quantified/alternated OOV operands
    behave correctly: ``X? / X* / X{0,n}`` take the epsilon (empty) path, while
    ``X+ / X{1,n}`` and a bare ``X`` produce zero matches. The fast postings
    path (``_simple_indexable_from_clause`` in engine.py) is what raises the
    recognised ``EmptyMatchError`` for the bare/sequence case so the
    boundary maps it to an empty result; this NFA path simply never matches,
    which is the same observable empty result.

    A genuinely malformed value (e.g. a non-string for ``=``) still raises the
    loud "nicht auflösbar" error -- that is a programmer/parse fault, not an
    OOV miss.
    """
    conds: List[Tuple[str, str, np.ndarray]] = []
    for c in clause.conds:
        if not corpus.has_attr(c.attr):
            raise ValueError(UNKNOWN_ATTRIBUTE.format(attr=c.attr))
        # Closed-class attributes (pos) have a small enumerable tagset. An exact
        # literal value outside that set is almost always a tagset mistake (e.g.
        # the STTS tag NN on a UPOS corpus) rather than a legitimate zero-result
        # query, so fail loudly with the valid inventory instead of returning a
        # silent empty result. Scoped to ``pos`` so open-class word/lemma zero
        # results are unaffected (see _check_closed_class_value).
        _check_closed_class_value(c, corpus)
        if c.op == "!=" and c.flags == "c":
            conds.extend(_case_insensitive_not_equal(c, corpus))
            continue
        vals = _value_to_type_ids(c, corpus, progress_cb=progress_cb)
        if vals is None:
            # ``=`` / ``in`` / ``~`` with a *recognisable* value (string/list)
            # that is simply out-of-vocabulary resolves to "nothing can equal an
            # absent value" -> a never-matching predicate, NOT an unresolvable
            # query. ``!=`` never reaches here (it returns the match-all sentinel
            # ``-1``), so a genuine ``None`` only remains for malformed value
            # types -> keep the loud "nicht auflösbar" error.
            if _is_oov_literal_miss(c):
                conds.append((c.attr, "=", _NEVER_MATCH_IDS))
                continue
            raise UnresolvableConditionError(
                UNRESOLVABLE.format(attr=c.attr, op=c.op, value=c.value)
            )
        if vals.size == 0:
            # Resolvable shape but zero matching ids (OOV set/regex/%c): same
            # never-matching contract as the ``None`` OOV case above.
            conds.append((c.attr, "=", _NEVER_MATCH_IDS))
            continue
        if c.op == "~":
            op = "in"
        elif c.op == "=" and c.flags == "c":
            # Case-insensitive equality resolves to the *set* of all lexicon
            # ids whose lowercased form matches, so it is lowered to ``in``
            # (the NFA supports membership but not a single-value ``=`` over a
            # multi-id set).
            op = "in"
        elif c.op == "=" and (
            isinstance(c.value, str) and _value_has_regex_metachars(c.value)
        ):
            # CWB-style double-quoted regex equality resolves to a *set* of ids
            # (one fullmatch per matching lexicon entry), so it is lowered to the
            # NFA membership op for the same reason as the ``%c`` case above.
            op = "in"
        else:
            op = c.op
        conds.append((c.attr, op, vals))
    return CompiledClause(conds=tuple(conds))


def _case_insensitive_not_equal(
    c: Cond, corpus: Corpus
) -> List[Tuple[str, str, np.ndarray]]:
    """Lower ``[attr!="x"%c]`` to one ``!=`` check per matching lexicon id.

    The conditions of a clause are a conjunction, so "no casing of x" is
    exactly "not id_1 and not id_2 ...". A value absent from the lexicon
    differs from every token (the match-all sentinel of plain ``!=``). A
    negated regular expression stays unsupported, as without ``%c``.
    """
    if not isinstance(c.value, str):
        raise UnresolvableConditionError(
            f"CQL Bedingung nicht auflösbar: {c.attr}{c.op}{c.value}"
        )
    if _value_has_regex_metachars(c.value):
        raise ValueError(_NEGATED_REGEX_MESSAGE)
    ids = _casefold_match_ids(corpus.lexicon(c.attr), [c.value])
    if ids.size == 0:
        return [(c.attr, "!=", np.asarray([-1], dtype=np.int32))]
    return [(c.attr, "!=", np.asarray([int(tid)], dtype=np.int32)) for tid in ids]


def _is_oov_literal_miss(c: Cond) -> bool:
    """True if ``c`` is a literal-op condition whose value is a well-formed but
    out-of-vocabulary literal (string for ``=``, list for ``in``, string for
    ``~`` / ``%c``)."""
    if c.op in {"=", "~"} or (c.op == "in"):
        if c.op == "in":
            return isinstance(c.value, (list, tuple))
        return isinstance(c.value, str)
    return False


# Attributes with a small, fully-enumerable tagset. An exact literal outside the
# set is treated as a tagset mistake (loud error), not a legitimate zero-result.
# Deliberately scoped to ``pos`` only: open-class attributes (word/lemma) have
# huge vocabularies where a genuine zero-result must stay a silent empty.
_CLOSED_CLASS_ATTRS = frozenset({"pos"})
# Cap how many valid tags we list back in the error so a large tagset (or a
# pathological lexicon) cannot produce an unbounded message.
_CLOSED_CLASS_SAMPLE = 24


def _closed_class_values(lex) -> List[str]:
    """All distinct, non-empty strings in an enumerable attribute lexicon."""
    out: List[str] = []
    seen: set[str] = set()
    for tid in _iter_lexicon_ids(lex):
        value = _lex_string_for_id(lex, int(tid))
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _check_closed_class_value(c: Cond, corpus: Corpus) -> None:
    """Raise a clear error for an out-of-tagset value on a closed-class attribute.

    Only positive *literal* membership (``=`` / ``in`` without regex/%c) on a
    closed-class attribute (``pos``) is checked: those are the cases that would
    otherwise silently resolve to zero hits and be indistinguishable from a
    legitimately-absent token. ``!=`` (match-all on OOV), ``~`` (regex), and the
    ``%c`` case-insensitive flag are intentionally left alone.
    """
    if c.attr not in _CLOSED_CLASS_ATTRS:
        return
    if c.flags == "c":
        return
    if c.op == "=":
        if not isinstance(c.value, str):
            return
        if _value_has_regex_metachars(c.value):
            return
        requested = [c.value]
    elif c.op == "in":
        if not isinstance(c.value, (list, tuple)):
            return
        requested = [v for v in c.value if isinstance(v, str)]
        if not requested:
            return
        # A mixed set with at least one valid tag is a reasonable query; only an
        # all-OOV set is flagged.
        if any(_value_has_regex_metachars(v) for v in requested):
            return
    else:
        return

    lex = corpus.lexicon(c.attr)
    # Hot path: a present tag resolves via the O(1) lexicon lookup, so we only
    # enumerate the full tagset (to build the helpful "valid values" hint) when a
    # requested value is genuinely missing.
    missing = [v for v in requested if _lex_get_id_literal(lex, v) is None]
    if not missing or len(missing) < len(requested):
        # Every requested value resolved, or at least one did (mixed set): not a
        # silent-empty tagset mistake.
        return
    valid = _closed_class_values(lex)
    sample = ", ".join(sorted(valid)[:_CLOSED_CLASS_SAMPLE])
    if len(valid) > _CLOSED_CLASS_SAMPLE:
        sample += ", ..."
    missing_text = ", ".join(repr(v) for v in missing)
    raise ValueError(
        lt(
            "Unbekanntes pos-Tag in CQL: {missing} ist kein gültiger Wert "
            "des Attributs '{attr}' in diesem Korpus. Gültige Werte: {valid}.",
            "Unknown pos tag in CQL: {missing} is not a valid value "
            "of the attribute '{attr}' in this corpus. Valid values: {valid}.",
        ).format(missing=missing_text, attr=c.attr, valid=sample)
    )


def best_indexable(
    clause: TokenClause, corpus: Corpus, *, progress_cb: Callable | None = None
) -> Optional[Indexable]:
    best: Optional[Indexable] = None
    for c in clause.conds:
        if c.op not in {'=', 'in', '~'}:
            continue
        if not corpus.has_attr(c.attr):
            continue
        vals = _value_to_type_ids(c, corpus, progress_cb=progress_cb)
        if vals is None or vals.size == 0:
            continue
        # estimate merged length as sum of individual list lengths (upper bound)
        idx = corpus.postings_index(c.attr)
        est = 0
        for tid in vals:
            est += idx.length(int(tid))
        cand = Indexable(attr=c.attr, type_ids=vals, est_len=int(est))
        if best is None or cand.est_len < best.est_len:
            best = cand
    return best


def _fast_lex_arrays(lex):
    # Unwrap FastLexiconAdapter -> underlying lexicon if present.
    base = getattr(lex, "_lexicon", lex)
    buckets = getattr(base, "_hash_buckets", None)
    entries = getattr(base, "_hash_entries", None)
    offsets = getattr(base, "_offsets", None)
    view = getattr(base, "_strings_view", None)
    bucket_bits = getattr(base, "_bucket_bits", None)
    if buckets is None or entries is None or offsets is None or view is None or bucket_bits is None:
        return None
    cache_sig = (id(buckets), id(entries), id(offsets), id(view), int(bucket_bits))
    cached = getattr(base, "_cqlhpc_fast_lex_arrays_cache", None)
    if cached is not None:
        try:
            if cached[0] == cache_sig:
                return cached[1]
        except Exception:
            pass
    try:
        # Structured-array field views have a stride equal to the whole record
        # size. The Cython lookup intentionally reads via raw data pointers for
        # speed, so it must receive dense arrays. Cache the copies per lexicon to
        # avoid per-query allocations while keeping the Python fallback unchanged.
        hashes = np.ascontiguousarray(entries["hash"], dtype=np.uint64)
        lexids = np.ascontiguousarray(entries["lexid"], dtype=np.uint32)
        buckets_arr = np.ascontiguousarray(buckets, dtype=np.uint64)
        offsets_arr = np.ascontiguousarray(offsets, dtype=np.uint64)
    except Exception:
        return None
    arrays = (buckets_arr, hashes, lexids, offsets_arr, view, int(bucket_bits))
    try:
        setattr(base, "_cqlhpc_fast_lex_arrays_cache", (cache_sig, arrays))
    except Exception:
        pass
    return arrays


def _lex_get_id(lex, value: str) -> Optional[int]:
    if _cy_lex_lookup_id is not None:
        arrays = _fast_lex_arrays(lex)
        if arrays is not None:
            buckets, hashes, lexids, offsets, view, bucket_bits = arrays
            try:
                tid = _cy_lex_lookup_id(buckets, hashes, lexids, offsets, view, bucket_bits, value)
                if tid:
                    return int(tid)
            except Exception:
                pass
    if hasattr(lex, "get_id"):
        try:
            tid = lex.get_id(value)
            return int(tid) if tid else None
        except Exception:
            return None
    if hasattr(lex, "str_to_id"):
        tid = lex.str_to_id.get(value)
        return int(tid) if tid is not None else None
    return None


def _unescape_literal(value: str) -> str:
    """Strip CQL escape backslashes from a literal value (``\\.`` -> ``.``).

    The lexer preserves backslashes in string literals so regex values
    (op ``~``) keep their metacharacter escapes. For *literal* operators
    (``=``/``!=``/``in``) an escaped value like ``\\.`` must still be able
    to find the stored token ``.`` in the lexicon. A trailing lone
    backslash is kept as-is (``\\(.)`` requires a following character).
    """
    return re.sub(r"\\(.)", r"\1", value)


def _lex_get_id_literal(lex, value: str) -> Optional[int]:
    """Lexicon lookup for literal-op values: the unescaped form first.

    In a CQL value ``\\|`` is the escaped pipe and ``\\.`` the escaped
    period. A corpus with escaped Markdown can also contain the rare tokens
    ``\\|``, ``\\.`` and ``\\[`` themselves. Looking up the raw form first
    would make [word="\\|"] count those tokens instead of the pipes (10
    instead of 272,832 on a corpus of 142 million tokens). The token ``\\.``
    itself is written ``"\\\\\\."``. The raw form stays the fallback when the
    unescaped one is missing. Only if BOTH miss is the value truly
    out-of-vocabulary (callers then apply the OOV rules).
    """
    if "\\" in value:
        tid = _lex_get_id(lex, _unescape_literal(value))
        if tid is not None:
            return tid
    return _lex_get_id(lex, value)


def _casefold_match_ids(lex, targets) -> np.ndarray:
    """All lexicon ids whose lowercased string equals any lowercased target.

    Backs case-insensitive (``%c``) literal matching. Scans the lexicon once
    (the same scan the regex path uses) and compares ``str.lower`` forms, so it
    catches German sentence-initial capitalisation (Dass, DASS -> dass).

    ``str.lower``, not ``str.casefold``: casefold folds ß to ss, and
    [word="daß"%c] would also count every "dass". ``str.lower`` keeps ß and ss
    apart like the regex branch with "(?i)" and folds the capital sharp s to
    ß. The same comparison as ``candyconc.domain.query_parser.casefold_key``.
    Returns a sorted, unique int32 id array (possibly empty).
    """
    texte = [t for t in targets if isinstance(t, str)]
    ids = _kleinschreibung_gleich(lex, {_unescape_literal(t).lower() for t in texte})
    if ids.size == 0 and any("\\" in t for t in texte):
        # Wie ``_lex_get_id_literal``: die rohe Form nur als Rueckfall.
        ids = _kleinschreibung_gleich(lex, {t.lower() for t in texte})
    return ids


def _kleinschreibung_gleich(lex, wanted) -> np.ndarray:
    if not wanted:
        return np.empty((0,), dtype=np.int32)
    out: List[int] = []
    for tid in _iter_lexicon_ids(lex):
        value = _lex_string_for_id(lex, int(tid))
        if value and value.lower() in wanted:
            out.append(int(tid))
    if not out:
        return np.empty((0,), dtype=np.int32)
    return np.asarray(sorted(set(out)), dtype=np.int32)


# CWB-style: a double-quoted attribute value is a regex by default. We keep
# plain literals (no metacharacters) on the fast exact-id lookup path, but route
# any value carrying an UNESCAPED regex metacharacter through the same
# fully-anchored lexicon regex match the ``~`` operator uses. This is what makes
# ``[word="Leut.*"]`` / ``[word="Leute|Leuten"]`` / ``[word="Leut[ez]"]`` /
# anchored ``^Leute$`` actually match instead of silently returning zero hits.
#
# A backslash-escaped metacharacter (``\.``) is a LITERAL, not a pattern: it must
# stay on the escaped-literal lookup path (the pre-existing P0 contract), so the
# scan skips the char after a backslash and ``\`` itself is not a trigger.
_REGEX_METACHARS = frozenset(".*+?|()[]{}^$")


def _value_has_regex_metachars(value: str) -> bool:
    i = 0
    n = len(value)
    while i < n:
        if value[i] == "\\":
            i += 2  # the escaped char is a literal, not a pattern metachar
            continue
        if value[i] in _REGEX_METACHARS:
            return True
        i += 1
    return False


@lru_cache(maxsize=16)
def _ohne_lemmatisierer_gebaut(meta_pfad: str, _stand: int) -> bool:
    try:
        meta = json.loads(Path(meta_pfad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(meta.get("spacy_model") or "").startswith("blank")


def lemma_ist_kleingeschriebene_wortform(corpus: Corpus) -> bool:
    """Ohne Lemmatisierer gebaut ist lemma die kleingeschriebene Wortform.

    build_fast_index_from_parquet setzt fuer blank-Pipelines tok.lemma_ =
    tok.lower_, und die Korpuskarte sagt dem Modell "lemma: kleingeschriebene
    Wortform". Dieselbe Quelle wie die Karte: spacy_model in
    index_build_meta.json.
    """
    pfad = getattr(getattr(corpus, "backend", None), "index_path", None)
    if pfad is None:
        return False
    meta = Path(pfad) / "index_build_meta.json"
    try:
        stand = meta.stat().st_mtime_ns
    except OSError:
        return False
    return _ohne_lemmatisierer_gebaut(str(meta), stand)


def _lemma_in_den_wertebereich(c: Cond, corpus: Corpus) -> Cond:
    """On an index whose lemma is the lowercased word form, lowercase a
    literal value like the index build does (str.lower).

    On an index built with blank:de, [lemma="Regierung"] would silently count
    0 and [lemma="regierung"] 31,523 on a corpus of 142 million tokens. No
    lemma of such an index contains an upper case letter, so the value
    "Regierung" can only mean "regierung" there. Regex values stay as they
    are, and %c folds anyway.
    """
    if c.attr != "lemma" or c.flags == "c" or not lemma_ist_kleingeschriebene_wortform(corpus):
        return c
    if c.op in {"=", "!="} and isinstance(c.value, str) and not _value_has_regex_metachars(c.value):
        return replace(c, value=c.value.lower())
    if c.op == "in" and isinstance(c.value, (list, tuple)):
        return replace(c, value=tuple(v.lower() if isinstance(v, str) else v for v in c.value))
    return c


def _value_to_type_ids(
    c: Cond, corpus: Corpus, *, progress_cb: Callable | None = None
) -> Optional[np.ndarray]:
    c = _lemma_in_den_wertebereich(c, corpus)
    lex = corpus.lexicon(c.attr)
    # A regex value with %c belongs in the regex branch below, which appends
    # "(?i)". This literal branch would look up "und|oder" as a word form and
    # silently return zero hits ([word="zudem|außerdem"%c] 0 instead of 42,973
    # on a corpus of 142 million tokens).
    regex_wert = c.op == "=" and isinstance(c.value, str) and _value_has_regex_metachars(c.value)
    if c.flags == "c" and c.op in {"=", "in"} and not regex_wert:
        # Case-insensitive literal(s): resolve to the set of all matching ids.
        # ``=``%c carries a single string value; ``in``%c carries a list.
        if c.op == "=":
            if not isinstance(c.value, str):
                return None
            targets = [c.value]
        else:
            if not isinstance(c.value, (list, tuple)):
                return None
            targets = c.value
        return _casefold_match_ids(lex, targets)
    if c.flags == "c" and c.op == "!=":
        # "token whose lowercased form != X" is a negated set, which a single
        # id array cannot express. compile_clause lowers it to one ``!=`` per
        # id (_case_insensitive_not_equal) before it would reach this point.
        raise ValueError(lt(
            "Case-insensitive '!=' (z.B. [word!=\"x\"%c]) wird noch nicht "
            "unterstützt. Bitte ein positives Muster (=, in, ~) verwenden.",
            "Case-insensitive '!=' (e.g. [word!=\"x\"%c]) is not supported "
            "yet. Use a positive pattern (=, in, ~).",
        ))
    if c.op in {'=', '!='}:
        if not isinstance(c.value, str):
            return None
        if _value_has_regex_metachars(c.value):
            # CWB-style double-quoted regex. ``=`` resolves to the SET of all
            # lexicon ids whose string fully matches the pattern (lowered to the
            # NFA ``in`` op in ``compile_clause``); an empty set is an honest
            # zero-result, exactly like the ``~`` operator.
            #
            # ``!=`` with a regex would need a negated-set membership test the
            # NFA runner does not provide (same gap as ``[x!="…"%c]``), so we
            # fail loudly instead of silently matching the wrong tokens.
            if c.op == '!=':
                raise ValueError(_NEGATED_REGEX_MESSAGE)
            pattern = str(c.value)
            if c.flags == "c":
                pattern = "(?i)" + pattern
            return _regex_to_type_ids(
                pattern, lex, attr=c.attr, corpus=corpus, progress_cb=progress_cb
            )
        tid = _lex_get_id_literal(lex, c.value)
        if tid is None:
            # Out-of-vocabulary value.
            #   ``=``  : nothing can equal an absent value -> no matches.
            #   ``!=`` : every token differs from an absent value -> match all.
            # For ``!=`` we emit a sentinel id (-1) that no real token id can
            # equal, so ``tv != -1`` holds for every token. This keeps the
            # value array non-empty (the matcher reads ``values[off]``).
            if c.op == '!=':
                return np.asarray([-1], dtype=np.int32)
            return None
        return np.asarray([tid], dtype=np.int32)

    if c.op == 'in':
        if not isinstance(c.value, (list, tuple)):
            return None
        # The Cython bulk lookup cannot retry escaped values individually;
        # fall through to the per-value loop when any value needs the
        # unescape fallback (rare: only values containing a backslash).
        has_escapes = any(isinstance(v, str) and "\\" in v for v in c.value)
        if _cy_lex_lookup_ids is not None and not has_escapes:
            arrays = _fast_lex_arrays(lex)
            if arrays is not None:
                buckets, hashes, lexids, offsets, view, bucket_bits = arrays
                try:
                    ids = _cy_lex_lookup_ids(buckets, hashes, lexids, offsets, view, bucket_bits, c.value)
                    if ids.size:
                        ids = ids[ids > 0]
                        if ids.size:
                            return np.unique(ids.astype(np.int32, copy=False))
                except Exception:
                    pass
        ids: List[int] = []
        for v in c.value:
            if not isinstance(v, str):
                continue
            tid = _lex_get_id_literal(lex, v)
            if tid is None:
                continue
            ids.append(tid)
        if not ids:
            return np.empty((0,), dtype=np.int32)
        arr = np.asarray(sorted(set(ids)), dtype=np.int32)
        return arr

    if c.op == '~':
        if not isinstance(c.value, str):
            return None
        pattern = str(c.value)
        if c.flags == "c":
            # Inline-flag the pattern so every downstream regex path (native
            # lexicon match, Python fallback scan, candidate prefilter) compiles
            # it case-insensitively. The backend candidate prefilter is bypassed
            # for IGNORECASE patterns, so this stays correct there too.
            pattern = "(?i)" + pattern
        return _regex_to_type_ids(pattern, lex, attr=c.attr, corpus=corpus, progress_cb=progress_cb)

    return None


_MAX_REGEX_TYPES = int(os.environ.get("CANDYCONC_MAX_REGEX_TYPES", "200000"))
_MAX_REGEX_FREQ = int(os.environ.get("CANDYCONC_MAX_REGEX_FREQ", "5000000"))


def _regex_redos_risk(pattern: str) -> bool:
    """Detect classic nested-unbounded-quantifier backtracking traps."""
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return False
    unbounded = sre_parse.MAXREPEAT

    def _contains_unbounded(sub) -> bool:
        for op, val in sub:
            if op == sre_parse.MAX_REPEAT:
                if val[1] == unbounded or _contains_unbounded(val[-1]):
                    return True
            elif op == sre_parse.SUBPATTERN:
                if _contains_unbounded(val[-1]):
                    return True
            elif op == sre_parse.BRANCH:
                if any(_contains_unbounded(branch) for branch in val[1]):
                    return True
        return False

    def _walk(sub) -> bool:
        for op, val in sub:
            if op == sre_parse.MAX_REPEAT:
                if val[1] == unbounded and _contains_unbounded(val[-1]):
                    return True
                if _walk(val[-1]):
                    return True
            elif op == sre_parse.SUBPATTERN:
                if _walk(val[-1]):
                    return True
            elif op == sre_parse.BRANCH:
                if any(_walk(branch) for branch in val[1]):
                    return True
        return False

    return _walk(parsed)



def _woertlich(muster: str) -> str:
    """Das Muster als woertliche Zeichenfolge, wenn es nur aus Satz- und
    Sonderzeichen besteht und mindestens einen Regex-Operator enthaelt, sonst ""."""
    muster = str(muster or "")
    if not muster or "\\" in muster or any(z.isalnum() for z in muster):
        return ""
    if not any(z in ".?*+()[]{}|^$" for z in muster):
        return ""
    return "".join("\\" + z if z in ".?*+()[]{}|^$" else z for z in muster)


# Words the callers of regex_zu_gross pass in German, with their English form.
_REGEX_ART = {"Regex": lt("Regex", "regex"), "Wildcard": lt("Wildcard", "wildcard")}
_REGEX_DIMENSION = {"Tokens": lt("Tokens", "tokens"), "Typen": lt("Typen", "types")}


def regex_zu_gross(*, gemessen: int, grenze: int, dimension: str,
                   muster: str = "", art: str = "Regex") -> RuntimeError:
    """Die Absage nennt, WIE WEIT das Muster daneben lag.

    A bare "Regex Treffer zu gross. Bitte Suchmuster einschraenken." leaves
    a caller who does not know the order of magnitude only guessing, and
    every guess costs another call. In batches of analysis questions on a
    273-million-token corpus this refusal occurred two to four times per
    batch.

    The refusal itself stays, it only becomes readable. The substring
    "Regex Treffer zu gross" is kept because the error classification of the
    routes checks for it.
    """
    def _zahl(n: int):
        # German and English digit grouping of the same number.
        return lt(f"{int(n):,}".replace(",", "."), f"{int(n):,}")

    faktor = gemessen / grenze if grenze > 0 else 0.0
    teil = lt(" fuer {muster!r}", " for {muster!r}").format(muster=muster) if muster else ""
    # A pattern of punctuation only that contains a period almost always
    # means the character itself. A model that writes [word="."] for the
    # sentence period would otherwise get only "einschraenken" back, again and
    # again (tests/backend/test_regex_refusal_names_literal_char.py).
    woertlich = _woertlich(muster) if art == "Regex" and "." in muster else ""
    hinweis = lt(
        " Im Regex steht '.' fuer ein beliebiges Zeichen, das Zeichen "
        "selbst schreibt sich [word=\"{literal}\"].",
        " In a regex, '.' stands for any character. The character "
        "itself is written [word=\"{literal}\"].",
    ).format(literal=woertlich) if woertlich else ""
    return RuntimeError(
        lt(
            "{art} Treffer zu gross{teil}: {gemessen} {dimension} gegen "
            "eine Grenze von {grenze} ({faktor}-fach). "
            "Bitte Suchmuster einschraenken.{hinweis}",
            "Too many {art} hits{teil}: {gemessen} {dimension} against "
            "a limit of {grenze} ({faktor} times). "
            "Narrow the search pattern.{hinweis}",
        ).format(
            art=_REGEX_ART.get(art, art),
            teil=teil,
            gemessen=_zahl(gemessen),
            dimension=_REGEX_DIMENSION.get(dimension, dimension),
            grenze=_zahl(grenze),
            faktor=lt(f"{faktor:.1f}".replace(".", ","), f"{faktor:.1f}"),
            hinweis=hinweis,
        )
    )

def _sum_freqs_for_ids(lex, ids: np.ndarray) -> int:
    freq_many = getattr(lex, "get_freqs_for_ids", None)
    if not callable(freq_many):
        base_lex = getattr(lex, "_lexicon", None)
        freq_many = getattr(base_lex, "get_freqs_for_ids", None)
    if callable(freq_many):
        return int(freq_many(ids.astype(np.int32, copy=False)).sum(dtype=np.int64))
    get_freq = getattr(lex, "get_freq", None)
    if get_freq is None:
        return 0
    total = 0
    for tid in ids.tolist():
        total += int(get_freq(int(tid)))
        if total > _MAX_REGEX_FREQ:
            break
    return total


def _iter_lexicon_ids(lex) -> range:
    id_to_str = getattr(lex, "id_to_str", None)
    if id_to_str is not None:
        return range(0, len(id_to_str))
    vocab_size = int(getattr(lex, "vocab_size", 0) or 0)
    return range(1, vocab_size + 1)


def _lex_string_for_id(lex, tid: int) -> str:
    get_string = getattr(lex, "get_string", None)
    if callable(get_string):
        return str(get_string(int(tid)))
    id_to_str = getattr(lex, "id_to_str", None)
    if id_to_str is not None and 0 <= int(tid) < len(id_to_str):
        return str(id_to_str[int(tid)])
    return ""


def _regex_scan_type_ids(
    lex,
    rex: re.Pattern,
    min_len: int,
    max_len: Optional[int],
    *,
    candidates: Optional[np.ndarray] = None,
) -> np.ndarray:
    if candidates is None:
        iterator = _iter_lexicon_ids(lex)
    else:
        iterator = (int(tid) for tid in candidates.tolist())
    out: list[int] = []
    for tid in iterator:
        value = _lex_string_for_id(lex, int(tid))
        if not value:
            continue
        if len(value) < min_len:
            continue
        if max_len is not None and len(value) > max_len:
            continue
        if rex.fullmatch(value):
            out.append(int(tid))
    return np.asarray(out, dtype=np.int32)


def _regex_to_type_ids(
    pattern: str,
    lex,
    *,
    attr: Optional[str] = None,
    corpus: Optional[Corpus] = None,
    progress_cb: Callable | None = None,
    deckel: bool = True,
) -> Optional[np.ndarray]:
    """``deckel=False`` nur fuer reine Zaehlungen ohne Positionen.

    Die Grenzen schuetzen die Positionsauswertung. Eine Korpuszaehlung einer
    einzelnen Zelle braucht keine Positionen, nur die Summe der Typfrequenzen,
    und die Absage nannte diese Summe schon in ihrem Text."""
    has_native_shape = hasattr(lex, "offsets") and hasattr(lex, "strings_view")
    has_python_shape = hasattr(lex, "id_to_str") or hasattr(lex, "get_string")
    if not has_native_shape and not has_python_shape:
        raise RuntimeError("Regex erfordert Fast Index Lexikon.")
    backend = getattr(corpus, "backend", None) if corpus is not None else None
    # Reject patterns that match only an empty string. For literal symbols
    # such as |, explain the required escaping. Pure anchors such as ^$
    # refer to an empty token and need no literal-symbol suggestion.
    if pattern and _regex_width(pattern) == (0, 0):
        woertlich = _woertlich(pattern) if pattern.strip("^$") else ""
        raise ValueError(
            f"Regex Muster {pattern!r} trifft nur die leere Zeichenfolge und damit kein Token."
            + (f" Im Regex ist das ein Operator, das Zeichen selbst schreibt sich [word=\"{woertlich}\"]." if woertlich else "")
        )
    if progress_cb is not None:
        progress_cb(f"Regex Scan gestartet: {pattern}")
    if backend is not None and attr is not None and hasattr(backend, "_regex_ids"):
        try:
            ids = backend._regex_ids(attr, pattern)
        except Exception:
            ids = None
        else:
            if ids.size == 0:
                return np.empty((0,), dtype=np.int32)
            total_freq = _sum_freqs_for_ids(lex, ids)
            if deckel and total_freq > _MAX_REGEX_FREQ:
                raise regex_zu_gross(gemessen=int(total_freq),
                                     grenze=int(_MAX_REGEX_FREQ),
                                     dimension="Tokens", muster=str(pattern))
            if deckel and ids.size > _MAX_REGEX_TYPES:
                raise regex_zu_gross(gemessen=int(ids.size),
                                     grenze=int(_MAX_REGEX_TYPES),
                                     dimension="Typen", muster=str(pattern))
            if progress_cb is not None:
                progress_cb(f"Narrowing down to {int(ids.size)} Typen, {int(total_freq)} Tokens - processing")
            return ids.astype(np.int32, copy=False)
    # ReDoS guard: this path compiles with Python's backtracking ``re`` and scans
    # the whole lexicon with fullmatch, so a nested-unbounded-quantifier pattern
    # ((a+)+ ...) would hang the worker before the post-scan caps run. Reject it.
    if _regex_redos_risk(pattern):
        raise ValueError(lt(
            "Regex mit verschachtelten unbeschraenkten Quantoren (z.B. (a+)+) ist "
            "nicht erlaubt (Gefahr katastrophalen Backtrackings). Bitte das Muster "
            "vereinfachen.",
            "Regex with nested unbounded quantifiers (e.g. (a+)+) is "
            "not allowed (risk of catastrophic backtracking). Simplify the "
            "pattern.",
        ))
    try:
        rex = re.compile(pattern)
    except Exception as exc:
        # A model that writes [word="*"] for the list stars in a corpus would
        # otherwise get only "Ungültiges Regex Muster: *", again and again. As
        # for the period (regex_zu_gross), the refusal names how to write the
        # character itself.
        woertlich = _woertlich(pattern)
        raise ValueError(
            lt("Ungültiges Regex Muster: {pattern}", "Invalid regex pattern: {pattern}").format(pattern=pattern)
            + (lt(
                " Im Regex ist das ein Operator, das Zeichen selbst schreibt sich [word=\"{literal}\"].",
                " In a regex this is an operator. The character itself is written [word=\"{literal}\"].",
            ).format(literal=woertlich) if woertlich else "")
        ) from exc
    min_len, max_len = _regex_width(pattern)
    ids = None
    ids_from_cache = False
    cache_key = (attr, pattern) if attr is not None else None
    regex_cache = getattr(backend, "_regex_cache", None) if backend is not None else None
    if regex_cache is not None and cache_key is not None:
        try:
            ids = regex_cache.get(cache_key)
            ids_from_cache = ids is not None
        except Exception:
            ids = None
            ids_from_cache = False
    if ids is None and backend is not None and attr is not None and hasattr(backend, "_regex_candidates"):
        try:
            ignorecase = bool(getattr(rex, "flags", 0) & re.IGNORECASE)
            if not ignorecase:
                ids = backend._regex_candidates(attr, pattern, min_len, max_len)
        except Exception:
            ids = None
    if ids is None:
        if lexicon_match_regex is None or not has_native_shape:
            ids = _regex_scan_type_ids(lex, rex, min_len, max_len)
        else:
            ids = lexicon_match_regex(lex.offsets, lex.strings_view, rex, min_len, max_len)
    elif not ids_from_cache:
        if lexicon_match_regex_ids is None or not has_native_shape:
            ids = _regex_scan_type_ids(lex, rex, min_len, max_len, candidates=ids)
        else:
            ids = lexicon_match_regex_ids(lex.offsets, lex.strings_view, ids, rex, min_len, max_len)
    if regex_cache is not None and cache_key is not None:
        try:
            regex_cache.set(cache_key, ids)
        except Exception:
            pass
    if ids.size == 0:
        return np.empty((0,), dtype=np.int32)
    total_freq = _sum_freqs_for_ids(lex, ids)
    if deckel and total_freq > _MAX_REGEX_FREQ:
        raise regex_zu_gross(gemessen=int(total_freq), grenze=int(_MAX_REGEX_FREQ),
                             dimension="Tokens", muster=str(pattern))
    if deckel and ids.size > _MAX_REGEX_TYPES:
        raise regex_zu_gross(gemessen=int(ids.size), grenze=int(_MAX_REGEX_TYPES),
                             dimension="Typen", muster=str(pattern))
    if progress_cb is not None:
        progress_cb(f"Narrowing down to {int(ids.size)} Typen, {int(total_freq)} Tokens - processing")
    return ids.astype(np.int32, copy=False)


def _regex_width(pattern: str) -> Tuple[int, Optional[int]]:
    try:
        parsed = sre_parse.parse(pattern)
        min_len, max_len = parsed.getwidth()
        # Python versions disagree on the concrete "unbounded" sentinel
        # returned by getwidth() (e.g. MAXREPEAT vs. 2**64). Keep the public
        # Python contract semantic: unbounded means None.
        if max_len >= sre_parse.MAXREPEAT:
            return int(min_len), None
        return int(min_len), int(max_len)
    except Exception:
        return 0, None


def _contains(sorted_vals: np.ndarray, x: int) -> bool:
    """Membership test on sorted int32 array."""
    if sorted_vals.size == 1:
        return int(sorted_vals[0]) == x
    # binary search
    lo = 0
    hi = int(sorted_vals.size)
    while lo < hi:
        mid = (lo + hi) >> 1
        v = int(sorted_vals[mid])
        if v < x:
            lo = mid + 1
        else:
            hi = mid
    return lo < int(sorted_vals.size) and int(sorted_vals[lo]) == x
