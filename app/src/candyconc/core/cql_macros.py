from __future__ import annotations

import re
import json
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import numpy as np

from candyconc.config import APP_CONFIG, get as get_config
from candyconc.core.index_signature import index_artifact_signature
from candyconc.core.word_vectors import (
    SERVICE_ERROR_MESSAGE,
    UNAVAILABLE_MESSAGE,
    WordVectorsServiceError,
    WordVectorsUnavailable,
    require_word_vectors,
)
from candyconc.services import embeddings
from candyconc import model_registry
from candyconc.i18n import lt

_SIM_CACHE_MAX = int(get_config("CANDYCONC_SIM_CACHE_SIZE", "64") or 64)
_SIM_DEFAULT_K = int(get_config("CANDYCONC_SIM_DEFAULT_K", "20") or 20)
_SIM_MAX_K = int(get_config("CANDYCONC_SIM_MAX_K", "2000") or 2000)
_SIM_MIN_SCORE = float(get_config("CANDYCONC_SIM_MIN_SCORE", "0.55") or 0.55)
_SIM_MAX_FETCH = int(get_config("CANDYCONC_SIM_MAX_FETCH", "5000") or 5000)
_SIM_EXCLUDE_STOPWORDS = get_config("CANDYCONC_SIM_EXCLUDE_STOPWORDS", "1") != "0"
_WORD_FAISS_CACHE_MAX = int(get_config("CANDYCONC_WORD_FAISS_CACHE_SIZE", "8") or 8)
_SIM_CACHE: "OrderedDict[tuple[object, ...], list[dict[str, object]]]" = OrderedDict()
# Keyed by ``(faiss_index_path, build_signature)`` so an in-place index rebuild
# (same path, new artifacts) invalidates the cached FAISS handle instead of
# serving a stale one (DT-CORE-LIFECYCLE). OrderedDict + size cap bounds growth
# across many corpora.
_WORD_FAISS_CACHE: "OrderedDict[tuple[str, int], tuple[object, np.ndarray, bool]]" = OrderedDict()
# Vector row -> corpus words, per (corpus, build signature, vector table).
_ROW_INDEX_CACHE: "OrderedDict[tuple, dict[int, list[str]]]" = OrderedDict()

_STRING_RE = r"\"(?:[^\"\\\\]|\\\\.)*\""
_SIM_ASSIGN_RE = re.compile(rf"\bsim\s*=\s*(?P<lit>{_STRING_RE})", re.IGNORECASE)
_K_ASSIGN_RE = re.compile(r"\bk\s*=\s*(\d+)", re.IGNORECASE)
_SIM_FUNC_RE = re.compile(
    rf"^\s*sim\s*\(\s*(?P<lit>{_STRING_RE}|'(?:[^'\\]|\\.)*')\s*(?:,\s*k\s*=\s*(?P<k>\d+)\s*)?\)\s*$",
    re.IGNORECASE,
)


def normalize_sim_syntax(query: str) -> str:
    """Normalize sim(...) shorthand and missing separators in sim clauses."""
    raw = (query or "").strip()
    if not raw:
        return ""
    raw_l = raw.lstrip()
    lead = len(raw) - len(raw_l)
    if raw_l.lower().startswith("cql:"):
        prefix = raw[:lead] + raw_l[:4]
        inner = raw_l[4:]
        return prefix + _normalize_sim_syntax_inner(inner)
    return _normalize_sim_syntax_inner(raw)


def normalize_query_input(raw_query: str) -> str:
    """Canonicalize common CQL entry variants to stable backend form.

    Supported aliases:
    - sim("...")            -> cql:[sim="..."]
    """
    raw = (raw_query or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if low.startswith("sim("):
        return f"cql:{normalize_sim_syntax(raw)}"
    if _looks_like_bare_cql(raw):
        return f"cql:{normalize_sim_syntax(raw)}"
    if low.startswith("cql:"):
        return f"cql:{normalize_sim_syntax(raw[4:].strip())}"
    return raw


def _looks_like_bare_cql(raw: str) -> bool:
    low = raw.lower()
    # Route the structural-wrapper forms to the CQL parser, not only the
    # ``within(``/``where(`` call forms. This is what lets the parser surface a
    # clear ParseError (HTTP 4xx) for CWB-style ``within <s>`` instead of
    # crashing with a 500 (the old plain-search fall-through choked on ``<s>``).
    if low.startswith("within(") or low.startswith("where("):
        return True
    # ``within``/``where`` followed by a structural or token form (``within <s>``,
    # ``within [word="a"]``) is CQL, so a malformed form surfaces a clear
    # ParseError (400) instead of crashing with a 500. The bare words, and the
    # words followed by other words, are English words for the plain search
    # ("where", "where it is").
    for keyword in ("within", "where"):
        if low.startswith(keyword + " ") and low[len(keyword):].lstrip()[:1] in {"<", "(", "[", '"'}:
            return True
    # A leading token clause is bare CQL only when it carries quotes or the
    # empty-token wildcard ``[]``. Unquoted legacy dependency/morph syntax
    # (``[pos=VERB] >nsubj [pos=NOUN]``) must NOT be captured here: it has its
    # own normalization path and would otherwise hit the strict CQL parser.
    # A group counts like its first cell. Otherwise ([word="a"] | [word="b"])
    # would go to the legacy parser and end in "Expected )", although the CQL
    # grammar has groups and alternation. The legacy group ([pos=ADJ] OR cat)
    # stays legacy because it has no quotes.
    if not raw.lstrip("( \t").startswith("["):
        return False
    if "[]" in raw:
        return True
    return '"' in raw or "'" in raw


def _normalize_sim_syntax_inner(raw: str) -> str:
    match = _SIM_FUNC_RE.match(raw)
    if match:
        lit = _coerce_to_double_quote(match.group("lit") or "")
        k = match.group("k")
        inner = f"sim={lit}"
        if k:
            inner += f"&k={k}"
        return f"[{inner}]"
    return _normalize_sim_in_brackets(raw)


def expand_sim_cql(query: str, backend_or_index) -> str:
    """Expand sim clauses to concrete CQL word-in sets."""
    normalized = normalize_sim_syntax(query)
    if not normalized:
        return normalized
    raw_l = normalized.lstrip()
    if raw_l.lower().startswith("cql:"):
        lead = len(normalized) - len(raw_l)
        normalized = raw_l[4:] if lead == 0 else normalized[:lead] + raw_l[4:]
    spans = _find_bracket_spans(normalized)
    if not spans:
        return normalized
    result_parts: list[str] = []
    last = 0
    for start, end in spans:
        result_parts.append(normalized[last : start + 1])
        inner = normalized[start + 1 : end]
        if "sim" in inner.lower():
            inner = _expand_sim_in_clause(inner, backend_or_index)
        result_parts.append(inner)
        last = end
    result_parts.append(normalized[last:])
    return "".join(result_parts)


def _normalize_sim_in_brackets(query: str) -> str:
    spans = _find_bracket_spans(query)
    if not spans:
        return query
    result_parts: list[str] = []
    last = 0
    for start, end in spans:
        result_parts.append(query[last : start + 1])
        inner = query[start + 1 : end]
        inner = _normalize_sim_clause(inner)
        result_parts.append(inner)
        last = end
    result_parts.append(query[last:])
    return "".join(result_parts)


def _normalize_sim_clause(clause: str) -> str:
    if "sim" not in clause.lower():
        return clause
    def _swap_single(match: re.Match[str]) -> str:
        prefix = match.group(1)
        value = match.group(2)
        return f'{prefix}"{_escape_cql(value)}"'

    clause = re.sub(r"(\bsim\s*=\s*)'([^']*)'", _swap_single, clause, flags=re.IGNORECASE)
    def _fix_k_sep(match: re.Match[str]) -> str:
        return f"{match.group(1)}&{match.group(2)}"

    clause = re.sub(
        rf"(\bsim\s*=\s*{_STRING_RE})\s+(\bk\s*=\s*\d+)",
        _fix_k_sep,
        clause,
        flags=re.IGNORECASE,
    )
    return clause


def _expand_sim_in_clause(clause: str, backend_or_index) -> str:
    cur = clause
    while True:
        match = _SIM_ASSIGN_RE.search(cur)
        if not match:
            break
        lit = match.group("lit")
        term = _unescape_cql(lit)
        k = _extract_k(cur)
        words = _similar_words(term, k, backend_or_index)
        if not words:
            raise RuntimeError(lt("Keine ähnlichen Wörter gefunden.", "No similar words found."))
        words_clause = _words_to_cql_set(words)
        cur = cur[: match.start()] + words_clause + cur[match.end() :]
        cur = _strip_k_assign(cur)
        cur = _cleanup_clause(cur)
    return cur


def _extract_k(clause: str) -> int:
    match = _K_ASSIGN_RE.search(clause)
    if not match:
        return _SIM_DEFAULT_K
    try:
        val = int(match.group(1))
    except Exception:
        return _SIM_DEFAULT_K
    val = max(1, val)
    if _SIM_MAX_K > 0:
        val = min(val, _SIM_MAX_K)
    return val


def _strip_k_assign(clause: str) -> str:
    return re.sub(r"(\s*&\s*|\s+)k\s*=\s*\d+", "", clause, flags=re.IGNORECASE)


def _cleanup_clause(clause: str) -> str:
    cleaned = re.sub(r"\s*&\s*&\s*", "&", clause)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"^&\s*", "", cleaned)
    cleaned = re.sub(r"\s*&$", "", cleaned)
    return cleaned


def _words_to_cql_set(words: Iterable[str]) -> str:
    items = ",".join(f"\"{_escape_cql(w)}\"" for w in words if w)
    return f"word in {{{items}}}"


def similar_words_scored(term: str, k: int, backend=None) -> list[dict[str, object]]:
    """Corpus-restricted distributional neighbours with cosine scores.

    Returns word, score and shared_query_vector (bool or None), ordered as the engine surfaces
    them (the seed term first, then neighbours in descending similarity). This is
    the scoring core promoted from the previous ``_similar_words`` body so the
    thesaurus surface (REST route, copilot tool) can keep the cosine scores that
    sim() query-expansion discards. ``_similar_words`` calls this and drops the
    scores, so sim() behaviour is unchanged.

    ``backend`` may be a Fast Index backend or a ``CorpusIndex`` (anything
    ``_resolve_backend`` understands).
    """
    if k <= 0:
        return []
    backend, corpus_key = _resolve_backend(backend)
    # Mix the index build signature into the cache key so an in-place rebuild of
    # the SAME corpus path invalidates stale sim() neighbours (DT-CORE-LIFECYCLE).
    build_sig = index_artifact_signature(corpus_key) if corpus_key else 0
    key = (
        term,
        int(k),
        "word",
        corpus_key,
        build_sig,
        round(float(_SIM_MIN_SCORE), 4),
        bool(_SIM_EXCLUDE_STOPWORDS),
    )
    cached = _SIM_CACHE.get(key)
    if cached is not None:
        _SIM_CACHE.move_to_end(key)
        return [dict(entry) for entry in cached]

    lex = getattr(backend, "lexicons", None).word if backend is not None else None
    if lex is None:
        raise RuntimeError(lt(
            "Word-Lexikon fehlt. Bitte Index neu bauen.",
            "Word lexicon missing. Rebuild the index.",
        ))

    # Decouple the QUERY-vector source from the candidate-lookup source. The
    # candidate lookup can come from a corpus FAISS word index (which embeds the
    # whole vocabulary with the same backend the index was built with). When such
    # an index exists we obtain the query vector from that corpus backend
    # (``embeddings.embed``) so the thesaurus works for jina/non-spaCy corpora,
    # falling back to spaCy only when no FAISS word index is present (or when the
    # corpus backend itself is spaCy). This keeps the spaCy path -- and therefore
    # ``_similar_words`` / sim() query expansion -- byte-identical.
    word_index = _load_word_faiss(backend)
    nlp = None
    vectors = None
    vec = None
    if word_index is not None:
        backend_vec = _embedding_backend_query_vector(term)
        if backend_vec is not None:
            vec = backend_vec
    if vec is None:
        # spaCy path: required when no usable corpus backend vector was produced.
        # The vectors are the corpus's own (those its word index was built from,
        # or those of its annotation pipeline), never another language's.
        nlp = _corpus_spacy_model(corpus_key)
        vec = nlp(term).vector
        if vec is None or not np.any(vec):
            alt = term.lower()
            if alt != term:
                vec = nlp(alt).vector
        if vec is None or not np.any(vec):
            raise RuntimeError(lt("Keine Embeddings für sim() gefunden.", "No embeddings found for sim()."))
        vectors = getattr(nlp.vocab, "vectors", None)
        if vectors is None or getattr(vectors, "n_keys", 0) <= 0:
            raise RuntimeError(lt("spaCy Modell hat keine Vektoren.", "The spaCy pipeline has no vectors."))
    vec = np.asarray(vec, dtype=np.float32).reshape(1, -1)
    query_vector = vec[0].copy()  # spaCy most_similar normalizes vec in place.
    seen: set[str] = set()
    results: list[dict[str, object]] = []

    def add_word(w: str, score: float | None = None, *, seed: bool = False) -> None:
        if not w or w in seen:
            return
        if any(ch.isspace() for ch in w):
            return
        if lex.get_id(w) <= 0:
            return
        if not seed:
            if score is not None and score < float(_SIM_MIN_SCORE):
                return
            if not _is_semantic_candidate(w, nlp):
                return
        seen.add(w)
        # The seed is its own nearest neighbour (cosine 1.0); use that when the
        # backend did not hand back an explicit score.
        eff_score = float(score) if score is not None else (1.0 if seed else float("nan"))
        candidate_vector = getattr(nlp.vocab[w], "vector", None) if nlp is not None else None
        results.append({
            "word": str(w), "score": eff_score,
            "shared_query_vector": (
                bool(np.array_equal(candidate_vector, query_vector)) if candidate_vector is not None else None
            ),
        })

    add_word(term, seed=True)
    target = int(max(1, k))

    if word_index is not None:
        idx_obj, word_ids, normalized = word_index
        query_vec = vec
        if normalized:
            norm = float(np.linalg.norm(query_vec))
            if norm > 0:
                query_vec = query_vec / norm
        try:
            dist, idxs = idx_obj.search(query_vec.astype(np.float32, copy=False), target)
        except Exception:
            dist, idxs = None, None
        hits = idxs[0] if idxs is not None else []
        hit_scores = dist[0] if dist is not None else []
        for offset, hit in enumerate(hits):
            if hit < 0:
                continue
            pos = int(hit)
            if pos >= len(word_ids):
                continue
            wid = int(word_ids[pos])
            w = lex.get_string(wid)
            score = None
            if normalized and offset < len(hit_scores):
                try:
                    score = float(hit_scores[offset])
                except Exception:
                    score = None
            add_word(str(w), score=score)
            if len(results) >= target:
                break

    if len(results) < target and nlp is not None and vectors is not None:
        row_index = _corpus_rows(nlp, lex, (corpus_key, build_sig))
        # Words that share the seed's vector row have no vector of their own
        # (the pruned table mapped them onto it). Their cosine 1.0 measures
        # nothing, so the seed row yields only the seed.
        seed_row = _vector_row(nlp, term)
        if seed_row is None and term.lower() != term:
            seed_row = _vector_row(nlp, term.lower())
        max_keys = int(getattr(vectors, "n_keys", 0))
        fetch_limit = max_keys
        if _SIM_MAX_FETCH > 0:
            fetch_limit = min(fetch_limit, int(_SIM_MAX_FETCH))
        fetch = min(fetch_limit, max(target * 5, target + 25))
        while len(results) < target and fetch > 0:
            # spaCy changed the return shape across versions:
            # older: (keys, scores), newer: (keys, scores, ...)
            similar_out = vectors.most_similar(vec, n=fetch)
            keys, scores = _similar_keys_and_scores(similar_out)
            if keys is None or len(keys) == 0:
                break
            score_row = scores[0] if scores is not None and len(scores) > 0 else None
            rows = _similar_rows(similar_out)
            for idx, key_id in enumerate(keys[0]):
                score = None
                if score_row is not None and idx < len(score_row):
                    try:
                        score = float(score_row[idx])
                    except Exception:
                        score = None
                # most_similar names each vector row by ONE of its keys, often
                # a rare spelling ("Töle" for the row of "Hund"). The corpus
                # words that share the row are the candidates.
                row_words = None
                if row_index is not None and rows is not None and idx < len(rows):
                    if seed_row is not None and int(rows[idx]) == seed_row:
                        continue
                    row_words = row_index.get(int(rows[idx]))
                for w in row_words or [nlp.vocab.strings[int(key_id)]]:
                    add_word(str(w), score=score)
                    if len(results) >= target:
                        break
                if len(results) >= target:
                    break
            if len(results) >= target or fetch >= fetch_limit:
                break
            if score_row is not None and len(score_row) > 0:
                try:
                    if float(score_row[-1]) < float(_SIM_MIN_SCORE):
                        break
                except Exception:
                    pass
            next_fetch = min(fetch_limit, fetch * 2)
            if next_fetch <= fetch:
                break
            fetch = next_fetch
    if not results:
        raise RuntimeError(
            lt(
                'Keine ähnlichen Korpuswörter für sim("{term}") '
                "oberhalb Score {score} gefunden.",
                'No similar corpus words found for sim("{term}") '
                "above score {score}.",
            ).format(term=term, score=f"{_SIM_MIN_SCORE:.2f}")
        )

    trimmed = [dict(entry) for entry in results[:target]]
    _SIM_CACHE[key] = [dict(entry) for entry in trimmed]
    _SIM_CACHE.move_to_end(key)
    while len(_SIM_CACHE) > _SIM_CACHE_MAX:
        _SIM_CACHE.popitem(last=False)
    return trimmed


def clear_sim_caches() -> None:
    """Evict the sim() neighbour cache and the FAISS word-index handle cache.

    Module-level entry point for cache invalidation (DT-CORE-LIFECYCLE). The
    build-signature mixed into the cache keys already makes a rebuild
    self-invalidating; this gives the server's reset / system-clear-cache path
    (DT-SERVER wires it) an explicit, immediate flush as well. Best-effort.
    """
    try:
        _SIM_CACHE.clear()
    except Exception:
        pass
    try:
        _WORD_FAISS_CACHE.clear()
    except Exception:
        pass
    try:
        _ROW_INDEX_CACHE.clear()
    except Exception:
        pass


def _similar_words(term: str, k: int, backend_or_index) -> list[str]:
    """Back-compat word list for sim() query-expansion (scores dropped)."""
    return [str(entry["word"]) for entry in similar_words_scored(term, k, backend_or_index)]


def _corpus_spacy_model(corpus_key: str):
    """The spaCy pipeline whose word vectors serve this corpus (core.word_vectors)."""
    if not corpus_key:
        raise WordVectorsUnavailable(UNAVAILABLE_MESSAGE)
    source = require_word_vectors(Path(corpus_key))
    if not source.pipeline:
        raise WordVectorsUnavailable(UNAVAILABLE_MESSAGE)
    try:
        return model_registry.get_spacy(source.pipeline)
    except (ImportError, OSError) as exc:
        raise WordVectorsServiceError(
            SERVICE_ERROR_MESSAGE
            + " "
            + lt(
                "Die Pipeline {pipeline} lässt sich nicht laden: {error}",
                "The pipeline {pipeline} cannot be loaded: {error}",
            ).format(pipeline=source.pipeline, error=str(exc))
        ) from exc


def _corpus_rows(nlp, lex, cache_key: tuple[str, int]) -> dict[int, list[str]] | None:
    """Vector row -> corpus words with that row, or None when the table has no rows.

    Pruned spaCy vector tables map many keys to one row. Built once per
    corpus, build and pipeline.
    """
    vectors = getattr(getattr(nlp, "vocab", None), "vectors", None)
    key2row = getattr(vectors, "key2row", None)
    if not isinstance(key2row, dict) or getattr(vectors, "mode", "default") != "default":
        return None
    key = (*cache_key, id(vectors))
    cached = _ROW_INDEX_CACHE.get(key)
    if cached is not None:
        _ROW_INDEX_CACHE.move_to_end(key)
        return cached
    from spacy.strings import hash_string

    index: dict[int, list[str]] = {}
    for wid in range(1, int(getattr(lex, "vocab_size", 0) or 0) + 1):
        word = lex.get_string(wid)
        if not word:
            continue
        row = key2row.get(hash_string(word))
        if row is not None and row >= 0:
            index.setdefault(int(row), []).append(word)
    _ROW_INDEX_CACHE[key] = index
    while len(_ROW_INDEX_CACHE) > _WORD_FAISS_CACHE_MAX:
        _ROW_INDEX_CACHE.popitem(last=False)
    return index


def _vector_row(nlp, word: str) -> int | None:
    """Row of ``word`` in a pruned spaCy vector table, None without one."""
    vectors = getattr(getattr(nlp, "vocab", None), "vectors", None)
    key2row = getattr(vectors, "key2row", None)
    if not isinstance(key2row, dict):
        return None
    from spacy.strings import hash_string

    row = key2row.get(hash_string(word))
    return int(row) if row is not None and row >= 0 else None


def _similar_rows(similar_out):
    """Row numbers from ``Vectors.most_similar`` (keys, rows, scores), else None."""
    if isinstance(similar_out, tuple) and len(similar_out) >= 3:
        rows = np.asarray(similar_out[1])
        return rows[0] if rows.ndim == 2 else rows
    return None


def _similar_keys_and_scores(similar_out) -> tuple[object | None, object | None]:
    if not isinstance(similar_out, tuple):
        return similar_out, None
    keys = similar_out[0] if len(similar_out) > 0 else None
    scores = None
    if len(similar_out) >= 3:
        scores = similar_out[2]
    elif len(similar_out) == 2:
        candidate = np.asarray(similar_out[1])
        if candidate.dtype.kind in {"f", "c"}:
            scores = similar_out[1]
    return keys, scores


def _is_semantic_candidate(word: str, nlp) -> bool:
    if not word or not any(ch.isalpha() for ch in word):
        return False
    if nlp is None:
        # No spaCy lexeme to inspect (non-spaCy backend via FAISS word index).
        # Candidates already passed the corpus-lexicon gate; accept them.
        return True
    try:
        lexeme = nlp.vocab[word]
    except Exception:
        return True
    if getattr(lexeme, "is_punct", False) or getattr(lexeme, "like_num", False):
        return False
    if _SIM_EXCLUDE_STOPWORDS and getattr(lexeme, "is_stop", False):
        return False
    return True


def _resolve_backend(backend_or_index):
    backend = None
    corpus_key = ""
    if backend_or_index is None:
        return None, ""
    if hasattr(backend_or_index, "fast_index"):
        backend = getattr(backend_or_index, "fast_index", None)
    else:
        backend = backend_or_index
    if backend is None:
        return None, ""
    corpus_key = str(getattr(backend, "index_path", ""))
    return backend, corpus_key


def _embedding_backend_query_vector(term: str) -> np.ndarray | None:
    """Query vector from the corpus embedding backend, or ``None``.

    Used only when a FAISS word index exists, to decouple the query-vector source
    from spaCy. Returns ``None`` for the spaCy backend (so the byte-identical
    spaCy code path runs instead) and for disabled/empty backends, and swallows
    backend failures so the caller can fall back to spaCy / surface the canonical
    "embeddings unavailable" error.
    """
    backend_name = str(get_config("CANDYCONC_EMB_BACKEND", "spacy") or "spacy").strip().lower()
    if backend_name in {"", "spacy", "none"}:
        return None
    try:
        arr = embeddings.embed([term], task="retrieval.query")
    except Exception:
        return None
    if arr is None:
        return None
    arr = np.asarray(arr, dtype=np.float32)
    if arr.size == 0 or not np.any(arr):
        return None
    return arr.reshape(1, -1)


def _load_word_faiss(backend) -> tuple[object, np.ndarray, bool] | None:
    if backend is None:
        return None
    index_root = Path(getattr(backend, "index_path", ""))
    if not index_root:
        return None
    idx_path = index_root / "faiss_word.index"
    ids_path = index_root / "word_ids.npy"
    if not idx_path.exists() or not ids_path.exists():
        return None
    # Key on (path, build_signature) so a rebuilt FAISS word index (same path,
    # new bytes) is reloaded rather than served stale (DT-CORE-LIFECYCLE). The
    # signature blends the index-artifact signature with the faiss/ids mtimes.
    build_sig = index_artifact_signature(index_root)
    for art in (idx_path, ids_path):
        try:
            mtime = art.stat().st_mtime_ns
        except OSError:
            continue
        if mtime > build_sig:
            build_sig = mtime
    cache_key = (str(idx_path), int(build_sig))
    cached = _WORD_FAISS_CACHE.get(cache_key)
    if cached is not None:
        _WORD_FAISS_CACHE.move_to_end(cache_key)
        return cached
    try:
        index_obj = model_registry.get_faiss_index(idx_path)
    except Exception:
        return None
    try:
        word_ids = np.load(ids_path, mmap_mode="r")
    except Exception:
        return None
    normalized = True
    meta_path = index_root / "embedding_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            info = meta.get("word_index") or {}
            if isinstance(info, dict) and "normalized" in info:
                normalized = bool(info.get("normalized"))
        except Exception:
            normalized = True
    try:
        nprobe_raw = getattr(APP_CONFIG, "CANDYCONC_FAISS_NPROBE", 0)
        nprobe = int(nprobe_raw or 0)
    except Exception:
        nprobe = 0
    if nprobe > 0 and hasattr(index_obj, "nprobe"):
        try:
            nlist = getattr(index_obj, "nlist", None)
            if nlist:
                nprobe = min(int(nprobe), int(nlist))
            index_obj.nprobe = int(nprobe)
        except Exception:
            pass
    _WORD_FAISS_CACHE[cache_key] = (index_obj, word_ids, normalized)
    _WORD_FAISS_CACHE.move_to_end(cache_key)
    while len(_WORD_FAISS_CACHE) > _WORD_FAISS_CACHE_MAX:
        _WORD_FAISS_CACHE.popitem(last=False)
    return _WORD_FAISS_CACHE[cache_key]


def _find_bracket_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    start = None
    quote = None
    escaped = False
    for idx, ch in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = None
            continue
        if ch in ("\"", "'"):
            quote = ch
            continue
        if ch == "[":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if ch == "]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    spans.append((start, idx))
                    start = None
            continue
    return spans


def _coerce_to_double_quote(literal: str) -> str:
    lit = literal.strip()
    if not lit:
        return "\"\""
    if lit.startswith("\"") and lit.endswith("\""):
        return lit
    if lit.startswith("'") and lit.endswith("'"):
        inner = lit[1:-1]
        return f"\"{_escape_cql(inner)}\""
    return f"\"{_escape_cql(lit)}\""


def _unescape_cql(literal: str) -> str:
    if len(literal) < 2:
        return literal
    if literal[0] not in ("\"", "'") or literal[-1] != literal[0]:
        return literal
    inner = literal[1:-1]
    buf: list[str] = []
    escaped = False
    for ch in inner:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        buf.append(ch)
    return "".join(buf)


def _escape_cql(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\"", "\\\"")
