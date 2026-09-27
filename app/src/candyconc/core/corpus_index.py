from pathlib import Path
from typing import Dict, Generator, Sequence, Set, Tuple
from collections import OrderedDict
import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from candyconc.config import get as get_config
from .fast_index_backend import FastIndexBackend
from .index_signature import index_open_signature
from .fast_index_native import strings_for_ids
from .meta_filters import metadata_fields as _metadata_fields
from .meta_filters import metadata_values as _metadata_values

import polars as pl
import numpy as np
from .counting_kernels import count_hashmap_svb, count_hashmap_svb_pos

_LOG_QUERIES = get_config("CANDYCONC_LOG_QUERIES", "0") == "1"
_LOGGER = logging.getLogger(__name__)


def _query_fingerprint(query: str) -> str:
    if not query:
        return "empty"
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


# Matches a leading global inline-flag group such as ``(?i)`` or ``(?im)``
# (group 1 = the flag letters). Only the standalone ``(?flags)`` form is a
# global flag group; scoped forms like ``(?i:...)`` are ordinary subgroups.
_LEADING_FLAG_GROUP_RE = re.compile(r"^\(\?([aiLmsux]+)\)")


def _with_ignorecase(pattern: str) -> str:
    """Return ``pattern`` compiled to ignore case.

    Modern Python rejects a global flag group that is not at the very start of
    the pattern, so we must not naively prepend a second ``(?i)`` when one
    already exists. Instead:

    * if a leading global flag group already enables ``i`` -> return unchanged;
    * if a leading global flag group exists without ``i`` -> merge ``i`` into it;
    * otherwise -> prepend a fresh ``(?i)`` group.

    This keeps the rewrite idempotent and valid for arbitrary user regexes.
    """
    if not pattern:
        return pattern
    m = _LEADING_FLAG_GROUP_RE.match(pattern)
    if m is not None:
        flags = m.group(1)
        if "i" in flags:
            return pattern
        return f"(?{flags}i){pattern[m.end():]}"
    return f"(?i){pattern}"


class _FastOnlyConn:
    def execute(self, *args, **kwargs):
        raise RuntimeError("Fast Index only. Bitte Builder nutzen.")

    def executemany(self, *args, **kwargs):
        raise RuntimeError("Fast Index only. Bitte Builder nutzen.")

    def fetchone(self, *args, **kwargs):
        raise RuntimeError("Fast Index only. Bitte Builder nutzen.")

    def fetchall(self, *args, **kwargs):
        raise RuntimeError("Fast Index only. Bitte Builder nutzen.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False




class CorpusIndex:
    """Fast Index only corpus wrapper.

    Parameters
    ----------
    index_path:
        Pfad zum Fast Index Verzeichnis oder zur Indexdatei.
    ranking_metric:
        Ranking metric for :func:`core.doc_search.document_search`. One of
        ``"tf"``, ``"tf-idf"``, or ``"bm25"``.
    read_only:
        When ``True`` (the default) opening the index performs no filesystem
        mutation: ``config.json`` is not written and a legacy
        ``cqlhpc_tuned.env`` is read/applied but neither migrated nor deleted.
        Persisting helpers (``set_*``) raise. Pass ``read_only=False`` for the
        admin/build paths that intentionally write index metadata.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        ranking_metric: str = "tf",
        read_only: bool = True,
    ) -> None:
        self.path = Path(db_path)
        if not self.path.is_dir():
            raise RuntimeError("Fast Index erwartet ein Verzeichnis mit meta.bin.")
        # Taken before the files are opened: a rebuild that races with this
        # constructor shows up as a changed signature on the next check.
        self.open_signature = index_open_signature(self.path)
        fast_path = self.path
        if not fast_path.exists():
            raise RuntimeError(f"Fast Index fehlt: {fast_path}")
        self.read_only = bool(read_only)
        self.fast_index = FastIndexBackend(fast_path)
        # Index manifest (R5): real manifest if present, else a version-0 manifest
        # synthesised from file presence so legacy indices keep opening.
        from .index_format import IndexManifest
        self.manifest = IndexManifest.load(self.path)
        self.conn = _FastOnlyConn()
        self.morph_coverage = 0.0
        self._config_path = fast_path / "config.json"
        self._config = self._load_config()
        self.ranking_metric = self._config.get("ranking_metric", ranking_metric)
        if "ranking_metric" not in self._config:
            self._config["ranking_metric"] = self.ranking_metric
            if not self.read_only:
                self._save_config()
        self._load_cqlhpc_env()
        # Lazily-built lowercase -> sorted id tuple maps (one per attr). These let
        # plain search, wildcard search and the case-folded frequency list share
        # exactly the ``str.lower`` semantics of CQL ``%c`` / the collocation
        # engine (DT-CORE-CASE-FREQ), so identical inputs give identical hit sets.
        # ß and ss stay separate (see query_parser.casefold_key).
        self._casefold_id_map: Dict[str, Dict[str, Tuple[int, ...]]] = {}
        # term_id -> globally-stable casefold-class representative id (the minimum
        # term_id in the class). DOCSET-INDEPENDENT by construction, so the folded
        # frequency_counts_docset maps a class to the SAME id regardless of which
        # docset / which counts — this is what keeps target/reference union1d
        # alignment correct in the docset-vs-docset keyness path
        # (C-casefold-counting-01).
        self._casefold_rep_map: Dict[str, Dict[int, int]] = {}
        # representative id -> id of the class member with the highest corpus
        # frequency. Only for LABELS: counting and alignment keep the
        # representative.
        self._casefold_label_map: Dict[str, Dict[int, int]] = {}
        self._casefold_lock = threading.Lock()

    def rebuilt_on_disk(self) -> bool:
        """True when the folder now holds a different build than the one opened.

        A missing folder (deleted, or between the two renames of a swap) is not
        a rebuild: the open handle keeps serving until a new build is in place.
        """
        opened = getattr(self, "open_signature", None)
        if not opened or not opened[2]:
            return False
        current = index_open_signature(self.path)
        if not current[2]:
            return False
        return current != opened

    @property
    def capabilities(self) -> Dict[str, bool]:
        """Capability flags for this index (from the manifest, or back-derived
        from file presence for legacy indices)."""
        return self.manifest.capabilities

    @property
    def is_legacy_index(self) -> bool:
        """True if this index predates the manifest (version-0, synthesised)."""
        return self.manifest.manifest_version == 0

    def _load_config(self) -> dict:
        if not self._config_path.exists():
            return {}
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Konfiguration unlesbar: {self._config_path}") from exc

    def _require_writable(self) -> None:
        if self.read_only:
            raise RuntimeError(
                "CorpusIndex ist read-only geöffnet; für schreibende Operationen "
                "mit read_only=False öffnen."
            )

    def _save_config(self) -> None:
        self._require_writable()
        self._config_path.write_text(json.dumps(self._config, indent=2), encoding="utf-8")

    @staticmethod
    def _parse_env_file(path: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        if not path.exists():
            return env
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key:
                env[key] = val
        return env

    def _apply_cqlhpc_env(self, env: dict[str, str]) -> None:
        if not env:
            return
        try:
            from candyconc.core import cql_engine

            cql_engine.clear_engine_cache()
        except Exception:
            pass

    def _load_cqlhpc_env(self) -> None:
        env: dict[str, str] = {}
        config_env = self._config.get("cqlhpc_env")
        if isinstance(config_env, dict):
            env.update({str(k): str(v) for k, v in config_env.items()})
        env_path = self.path / "cqlhpc_tuned.env"
        if env_path.exists() and not env:
            parsed = self._parse_env_file(env_path)
            if parsed:
                env.update(parsed)
                # Keep it in-memory either way so get_cqlhpc_env() is consistent.
                self._config["cqlhpc_env"] = dict(env)
                if not self.read_only:
                    # Migrate the legacy env file into config.json, then drop it.
                    self._save_config()
                    try:
                        env_path.unlink()
                    except Exception:
                        pass
        self._apply_cqlhpc_env(env)

    def get_cqlhpc_env(self) -> dict[str, str]:
        env = self._config.get("cqlhpc_env")
        if isinstance(env, dict):
            return {str(k): str(v) for k, v in env.items()}
        return {}

    def get_autotune_lock_ttl(self, default: int = 21600) -> int:
        value = self._config.get("autotune_lock_ttl_sec")
        try:
            return int(value)
        except Exception:
            return int(default)

    def set_autotune_lock_ttl(self, ttl_sec: int) -> None:
        self._require_writable()
        self._config["autotune_lock_ttl_sec"] = int(ttl_sec)
        self._save_config()

    def set_cqlhpc_env(self, env: Dict[str, str], *, source: str = "autotune") -> None:
        """Persist tuned CQLHPC env for this index and apply it immediately."""
        self._require_writable()
        clean = {str(k): str(v) for k, v in env.items() if str(k).startswith("CANDYCONC_CQLHPC_")}
        if not clean:
            return
        self._config["cqlhpc_env"] = dict(clean)
        self._config["cqlhpc_env_source"] = source
        self._config["cqlhpc_env_updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_config()
        self._apply_cqlhpc_env(clean)

    # ------------------------------------------------------------------
    # Public helpers ----------------------------------------------------
    def close(self) -> None:
        """Release the underlying Fast Index resources (DT-CORE-LIFECYCLE).

        Drives the close chain ``CorpusIndex -> FastIndexBackend -> token_store
        + lexicons + doc_metadata`` so an evicted/closed corpus frees its mmap
        file descriptors instead of leaking them (consumed by the server
        ``_LANG_INDICES`` eviction in DT-SERVER). Best-effort and idempotent.
        """
        # A cached CQL engine wraps this exact backend. Drop only this path before
        # closing its mmaps so reopening the corpus cannot reuse a dead engine.
        try:
            from candyconc.core.cql_engine import clear_engine_cache

            clear_engine_cache(self.path)
        except Exception:
            pass
        fast = getattr(self, "fast_index", None)
        if fast is not None and hasattr(fast, "close"):
            try:
                fast.close()
            except Exception:
                pass
        # Drop the per-attr casefold maps so a re-open rebuilds them.
        try:
            self._casefold_id_map.clear()
            self._casefold_rep_map.clear()
            self._casefold_label_map.clear()
        except Exception:
            pass

    def get_ranking_metric(self) -> str:
        """Return the configured ranking metric."""
        return self.ranking_metric

    def set_ranking_metric(self, metric: str) -> None:
        """Persist ``metric`` as ranking metric for this index."""
        self._require_writable()
        self.ranking_metric = metric
        self._config["ranking_metric"] = metric
        self._save_config()

    def token_count(self) -> int:
        return self.fast_index.token_store.token_count

    def lexicon_values(self, attr: str) -> list[str]:
        lex = self.fast_index._lexicon_for_attr(attr)
        if lex is None:
            return []
        ids = np.arange(1, lex.vocab_size + 1, dtype=np.uint32)
        strings = strings_for_ids(lex.offsets, lex.strings_view, ids, True)
        return [s for s in strings if s]

    def metadata_fields(self) -> list[str]:
        return _metadata_fields(self.fast_index)

    def metadata_values(
        self,
        field: str,
        *,
        filters: dict[str, object] | None = None,
        limit: int | None = None,
    ) -> list[str]:
        return _metadata_values(self.fast_index, str(field), filters=filters, limit=limit)

    # ------------------------------------------------------------------
    # KWIC queries ------------------------------------------------------
    def query(
        self,
        term: str,
        ctx: int = 5,
        *,
        path: str | None = None,
        version: int | None = None,
        limit: int | None = None,
    ) -> Generator[Dict[str, str], None, None]:
        """Yield KWIC rows for ``term`` with ``ctx`` words of context.

        ``path`` and ``version`` can be provided to restrict matches to a
        specific document revision.
        """
        if path is not None or version is not None:
            raise RuntimeError("Fast index unterstützt keine Pfad oder Versionsfilter")
        
        if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("CorpusIndex.query term_hash=%s ctx=%d", _query_fingerprint(term), int(ctx))
        
        rows = self.fast_index.kwic_rows(term, ctx, attr="word", limit=limit)
        for row in rows:
            row.setdefault("version", None)
            row.setdefault("start", 0)
            row.setdefault("end", 0)
            row.setdefault("media", None)
            yield row

    def query_morph(
        self, tag: str, ctx: int = 5
    ) -> Generator[Dict[str, str], None, None]:
        """Yield KWIC rows for tokens whose ``morph`` column contains ``tag``."""
        rows = self.fast_index.kwic_rows(tag, ctx, attr="morph")
        for row in rows:
            row.setdefault("start", 0)
            row.setdefault("end", 0)
            row.setdefault("media", None)
            yield row

    def query_entity(self, ent_type: str, ctx: int = 5) -> Generator[Dict[str, str], None, None]:
        """Yield KWIC rows for tokens with entity type ``ent_type``."""
        rows = self.fast_index.kwic_rows(ent_type, ctx, attr="ent")
        for row in rows:
            yield row

    def query_dependency(
        self,
        *,
        rel: str,
        head_word: str | None = None,
        dep_word: str | None = None,
        head_attr: tuple[str, str] | str | None = None,
        dep_attr: tuple[str, str] | str | None = None,
        ctx: int = 5,
    ) -> Generator[Dict[str, str], None, None]:
        """Yield rows for dependencies matching the given parameters."""
        rows = self.fast_index.query_dependency(
            rel=rel,
            head_word=head_word,
            dep_word=dep_word,
            head_attr=head_attr,
            dep_attr=dep_attr,
            ctx=ctx,
        )
        for row in rows:
            row.setdefault("start", 0)
            row.setdefault("end", 0)
            row.setdefault("media", None)
            yield row

    def query_metadata(
        self,
        term: str,
        *,
        date: str | None = None,
        genre: str | None = None,
        ctx: int = 5,
        limit: int | None = None,
    ) -> Generator[Dict[str, str], None, None]:
        """Yield KWIC rows filtered by optional ``date`` and ``genre``."""
        rows = self.fast_index.query_metadata(
            term, date=date, genre=genre, ctx=ctx, limit=limit
        )
        for row in rows:
            row.setdefault("start", 0)
            row.setdefault("end", 0)
            row.setdefault("media", None)
            yield row

    # ------------------------------------------------------------------
    # Sequence search --------------------------------------------------
    def sequence_positions(
        self, tokens: Sequence[str], *, case_insensitive: bool = True
    ) -> list[int]:
        """Return start positions of the literal ``tokens`` sequence (phrase).

        With ``case_insensitive`` True (the default) each slot matches the full
        case class (shared ``str.lower`` contract, ``ß`` and ``ss`` stay
        distinct). With False the phrase must match exactly (the backend's literal
        sequence path), so a bare phrase with ``case_insensitive=False`` is an
        exact-case match.
        """
        if not case_insensitive:
            positions = self.fast_index.sequence_positions(tokens)
        else:
            positions = self._sequence_positions_ci(tokens)
        return [int(p) for p in self._im_dokument(np.asarray(positions), len(tokens))]

    def _im_dokument(self, starts: np.ndarray, laenge: int) -> np.ndarray:
        """Only sequences whose last position lies in the document of their start.

        The position intersection alone knows no boundaries: "ist Deutsche"
        could count once across the end of one document and the start of the
        next, while within(<doc>, ...) of the same sequence counts 0.
        Sentence boundaries inside a document stay open because the fast
        index does not store them (folgenbereich.WORTFOLGE says so)."""
        grenzen = getattr(getattr(self.fast_index, "boundaries", None), "document", None)
        if laenge <= 1 or starts.size == 0 or not grenzen:
            return starts
        anfaenge = grenzen._positions
        if anfaenge.size == 0:
            return starts
        s = starts.astype(np.int64, copy=False)
        gleich = np.searchsorted(anfaenge, s, side="right") == np.searchsorted(
            anfaenge, s + (laenge - 1), side="right"
        )
        return starts[gleich]

    def _sequence_positions_ci(self, tokens: Sequence[str]) -> np.ndarray:
        """Case-insensitive phrase match over the shared casefold contract.

        Each token slot resolves to the UNION of every casefold-matching id's
        positions; slots are then combined with ``intersect_shifted`` (the same
        kernel the exact backend phrase path uses) so the whole phrase is matched
        case-insensitively without materialising the per-slot variants in CQL.
        """
        from .fast_index_native import intersect_shifted

        toks = [str(t) for t in tokens]
        if not toks:
            return np.zeros(0, dtype=np.uint32)
        token_count = int(self.fast_index.token_store.token_count)
        max_pos = token_count - len(toks)
        if max_pos < 0:
            return np.zeros(0, dtype=np.uint32)

        def _slot_positions(tok: str) -> np.ndarray:
            ids = self._casefold_ids(tok, attr="word")
            if ids.size == 0:
                return np.zeros(0, dtype=np.uint32)
            return self.fast_index._union_positions_for_ids("word", ids).astype(
                np.uint32, copy=False
            )

        base = _slot_positions(toks[0])
        if base.size == 0:
            return base
        base = base[base <= np.uint32(max_pos)]
        if base.size == 0 or len(toks) == 1:
            return base
        for offset, tok in enumerate(toks[1:], start=1):
            other = _slot_positions(tok)
            if other.size == 0:
                return np.zeros(0, dtype=np.uint32)
            base = intersect_shifted(base, other, offset, max_pos)
            if base.size == 0:
                return base
        return base.astype(np.uint32, copy=False)

    # ------------------------------------------------------------------
    # Frequency list ----------------------------------------------------
    def _lexicon_for_frequency_attr(self, attr: str):
        attr_norm = str(attr or "word").strip().lower()
        if attr_norm == "word":
            lex = self.fast_index.lexicons.word
        elif attr_norm == "lemma":
            lex = self.fast_index.lexicons.lemma
        elif attr_norm == "pos":
            lex = self.fast_index.lexicons.pos
        else:
            raise ValueError("Frequenz-Attribut muss word, lemma oder pos sein")
        if lex is None:
            raise RuntimeError(f"{attr_norm} Lexikon fehlt. Bitte Index neu bauen.")
        return attr_norm, lex

    def _sentinel_pos_counts(
        self, starts: np.ndarray | None = None, ends: np.ndarray | None = None
    ) -> np.ndarray:
        """Return a per-pos-tag histogram (``pos_id -> count``) of the ``|LBR|`` token.

        FIX-C (POS-FREQ-SENTINEL): the index-only ``|LBR|`` line-break sentinel is a
        first-class token that carries a POS tag (e.g. one occurrence tagged NOUN),
        so counting it inflates POS-tag frequencies above the canonical figures
        every other surface reports (NOUN 9741 vs 9740, VERB 4796 vs 4781). We
        resolve the sentinel word-id through the SAME shared seam the rows/count
        surfaces use (``query_runtime.linebreak_sentinel_word_id``; lazy import to
        avoid the core import cycle) and bincount the POS ids of its occurrences,
        so the POS-frequency paths can subtract exactly that contribution.

        ``starts``/``ends`` restrict the scan to selected document ranges (the
        docset path); when both are ``None`` the whole token stream is scanned and
        the result is cached, since the corpus is frozen.
        """
        from .query_runtime import linebreak_sentinel_word_id

        sentinel_id = linebreak_sentinel_word_id(self)
        pos_lex = self.fast_index.lexicons.pos
        if pos_lex is None:
            raise RuntimeError("POS Lexikon fehlt. Bitte Index neu bauen.")
        size = int(pos_lex.vocab_size) + 1
        whole = starts is None and ends is None
        if sentinel_id <= 0:
            return np.zeros(size, dtype=np.int64)
        if whole:
            cached = getattr(self, "_sentinel_pos_counts_cache", None)
            if cached is not None:
                return cached
        token_store = self.fast_index.token_store
        token_count = int(token_store.token_count)
        if whole:
            starts = np.zeros(1, dtype=np.int64)
            ends = np.asarray([token_count], dtype=np.int64)
        else:
            starts = np.asarray(starts, dtype=np.int64)
            ends = np.asarray(ends, dtype=np.int64)
        pos_ids = np.asarray(token_store.pos_ids, dtype=np.int64)
        word_stream = token_store.word_stream
        hist = np.zeros(size, dtype=np.int64)
        for start, end in zip(starts, ends):
            if end <= start:
                continue
            idx_range = np.arange(int(start), int(end), dtype=np.int64)
            word_ids = np.asarray(
                word_stream.get_ranges_packed_i32(idx_range, idx_range + 1),
                dtype=np.int64,
            )
            sel = word_ids == int(sentinel_id)
            if not sel.any():
                continue
            sentinel_pos = pos_ids[idx_range[sel]]
            sentinel_pos = sentinel_pos[(sentinel_pos > 0) & (sentinel_pos < size)]
            if sentinel_pos.size:
                hist += np.bincount(sentinel_pos, minlength=size).astype(np.int64)
        if whole:
            try:
                self._sentinel_pos_counts_cache = hist
            except Exception:  # pragma: no cover - read-only/exotic index objects
                pass
        return hist

    def frequency_list(
        self,
        *,
        stopwords: Sequence[str] | None = None,
        attr: str = "word",
        case_fold: bool = True,
    ) -> pl.DataFrame:
        """Return word/lemma/POS frequencies for the indexed corpus.

        With ``case_fold`` True (the default) surface forms are aggregated by the
        shared ``str.lower`` key (same contract as plain search / ``%c``, ``ß``
        and ``ss`` stay distinct): every case variant of a type is summed into ONE row,
        labelled with the global casefold representative surface form, so that
        ``sum(folded "dass") == term_positions("dass", case_insensitive=True).size``.
        With ``case_fold`` False the legacy per-surface-form list is returned.
        """
        attr_norm, lex = self._lexicon_for_frequency_attr(attr)
        freqs = lex.get_freqs_array()
        if freqs.size == 0:
            return pl.DataFrame([], schema=["word", "f"])
        if attr_norm == "pos":
            # FIX-C: exclude the index-only ``|LBR|`` sentinel's POS contribution so
            # the whole-corpus POS frequency matches the canonical figures every
            # other surface reports (NOUN 9740, VERB 4781), not the raw 9741/4796.
            sentinel_pos = self._sentinel_pos_counts()
            if sentinel_pos.any():
                freqs = freqs.astype(np.int64, copy=True)
                n = min(freqs.size, sentinel_pos.size)
                freqs[:n] = np.maximum(freqs[:n] - sentinel_pos[:n], 0)
        ids = np.nonzero(freqs)[0]
        ids = ids[ids > 0]
        if ids.size == 0:
            return pl.DataFrame([], schema=["word", "f"])
        if stopwords:
            stop_ids = np.fromiter(
                self._frequency_stop_ids(
                    attr_norm,
                    lex,
                    stopwords,
                    case_fold=case_fold,
                ),
                dtype=np.int32,
            )
            if stop_ids.size:
                ids = ids[~np.isin(ids, stop_ids)]
        if ids.size == 0:
            return pl.DataFrame([], schema=["word", "f"])
        ids = ids.astype(np.uint32, copy=False)
        words = strings_for_ids(lex.offsets, lex.strings_view, ids, True)
        counts = freqs[ids].astype(np.int64).tolist()
        if not case_fold:
            df = pl.DataFrame({"word": words, "f": counts})
            return df.sort("f", descending=True)
        folded = self._fold_freq_ids(ids, counts, attr_norm)
        df = pl.DataFrame(folded, schema=["word", "f"])
        return df.sort("f", descending=True)

    def _frequency_stop_ids(
        self,
        attr: str,
        lex,
        stopwords: Sequence[str],
        *,
        case_fold: bool,
    ) -> Set[int]:
        """Resolve stopwords with the same case contract as the result rows."""

        if not case_fold:
            return {
                int(term_id)
                for word in stopwords
                if word
                for term_id in [lex.get_id(str(word))]
                if int(term_id) > 0
            }
        from candyconc.domain.query_parser import casefold_key

        folded_ids = self._casefold_map(attr)
        return {
            int(term_id)
            for word in stopwords
            if word
            for term_id in folded_ids.get(casefold_key(str(word)), ())
            if int(term_id) > 0
        }

    def _fold_freq_ids(
        self,
        term_ids: Sequence[int],
        counts: Sequence[int],
        attr: str = "word",
    ) -> list[dict[str, object]]:
        """Aggregate ``(term_id, count)`` pairs by the global casefold key.

        Rows are keyed by :meth:`_casefold_representatives` and labelled by
        :meth:`_casefold_label_ids` (the most frequent spelling in the corpus),
        not the docset-local dominant form, so whole-corpus and async/docset
        frequency paths present the same surface spelling for the same class.
        """
        attr_norm, lex = self._lexicon_for_frequency_attr(attr)
        rep_map = self._casefold_representatives(attr_norm)
        totals: OrderedDict[int, int] = OrderedDict()
        for term_id, count in zip(term_ids, counts):
            tid = int(term_id)
            if tid <= 0:
                continue
            rep = rep_map.get(tid, tid)
            totals[rep] = totals.get(rep, 0) + int(count)
        if not totals:
            return []
        rep_ids = np.fromiter(totals.keys(), dtype=np.uint32)
        labels = self.casefold_labels(rep_ids, attr_norm)
        return [
            {"word": label, "f": int(totals[int(rep_id)])}
            for rep_id, label in zip(rep_ids, labels)
        ]

    def _doc_ranges_for_ids(self, doc_ids: Sequence[int]) -> tuple[np.ndarray, np.ndarray, int]:
        if not (self.fast_index.boundaries and self.fast_index.boundaries.document):
            raise RuntimeError("Dokumentgrenzen fehlen. Bitte Index neu bauen.")
        doc_bounds = self.fast_index.boundaries.document._positions
        if doc_bounds.size == 0:
            raise RuntimeError("Dokumentgrenzen leer. Bitte Index neu bauen.")
        token_count = int(self.fast_index.token_store.token_count)
        ids = np.asarray(doc_ids, dtype=np.int64)
        if ids.size == 0:
            return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.uint32), token_count
        ids = ids[(ids >= 0) & (ids < doc_bounds.size)]
        if ids.size == 0:
            return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.uint32), token_count
        starts = doc_bounds[ids].astype(np.uint32, copy=False)
        next_ids = ids + 1
        ends = np.empty_like(starts, dtype=np.uint32)
        mask = next_ids < doc_bounds.size
        if np.any(mask):
            ends[mask] = doc_bounds[next_ids[mask]].astype(np.uint32, copy=False)
        if np.any(~mask):
            ends[~mask] = np.uint32(token_count)
        return starts, ends, token_count

    def docset_token_count(self, doc_ids: Sequence[int]) -> int:
        starts, ends, _ = self._doc_ranges_for_ids(doc_ids)
        if starts.size == 0:
            return 0
        return int(np.sum(ends.astype(np.int64) - starts.astype(np.int64)))

    def analysetoken_je_dokument(self) -> np.ndarray:
        """Number of analysis tokens per document, counted once per process.

        An analysis token is what ``is_analyst_token`` lets through: at least
        one letter or digit, no |...| marker. Keyness computes on this set,
        and word rates use the same denominator. The raw token count contains
        punctuation, Markdown characters and line breaks whose share varies
        between the compared groups. On a corpus of human and machine-generated
        texts it is 29.4 percent for one generator and 13.7 percent for
        another, and 12.5 against 20.9 percent for human against AI texts in
        Easy German. The same word density would then give rates up to 22
        percent apart, and the same 126 hits could appear as 13.61 and as 11.2
        per million.

        Counted in sections at document boundaries so that the whole token
        stream never sits in memory. The result depends only on the frozen
        index and is cached on the object.
        """
        vorhanden = getattr(self, "_analysetoken_je_dokument_cache", None)
        if vorhanden is not None:
            return vorhanden
        from candyconc.analysis_defaults import is_analyst_token

        fast = self.fast_index
        if not (fast.boundaries and fast.boundaries.document):
            raise RuntimeError("Dokumentgrenzen fehlen. Bitte Index neu bauen.")
        anfaenge = np.asarray(fast.boundaries.document._positions, dtype=np.int64)
        token_count = int(fast.token_store.token_count)
        lex = fast.lexicons.word
        if lex is None:
            raise RuntimeError("Wort-Lexikon fehlt. Bitte Index neu bauen.")
        typen = int(lex.vocab_size)
        maske = np.zeros(typen + 1, dtype=bool)
        # Decode the lexicon in chunks: decoding all strings at once peaked at
        # 850 MB on a corpus of 250,535 documents and 142 million tokens.
        for von in range(1, typen + 1, 1 << 20):
            bis = min(typen, von + (1 << 20) - 1)
            woerter = strings_for_ids(
                lex.offsets, lex.strings_view,
                np.arange(von, bis + 1, dtype=np.uint32), True,
            )
            maske[von:bis + 1] = np.fromiter(
                (is_analyst_token(w) for w in woerter), dtype=bool,
                count=bis - von + 1)
        anzahl = int(anfaenge.size)
        enden = np.empty(anzahl, dtype=np.int64)
        if anzahl:
            enden[:-1] = anfaenge[1:]
            enden[-1] = token_count
        je_dokument = np.zeros(anzahl, dtype=np.int64)
        abschnitt = 1 << 24
        strom = fast.token_store.word_stream
        d = 0
        while d < anzahl:
            beginn = int(anfaenge[d])
            e = int(np.searchsorted(enden, beginn + abschnitt, side="right"))
            e = max(e, d + 1)
            schluss = int(enden[e - 1])
            if schluss > beginn:
                ids = np.asarray(strom.get_range_i32(beginn, schluss))
                ids = np.clip(ids, 0, typen)
                summe = np.zeros(schluss - beginn + 1, dtype=np.int64)
                np.cumsum(maske[ids], out=summe[1:])
                je_dokument[d:e] = (summe[enden[d:e] - beginn]
                                    - summe[anfaenge[d:e] - beginn])
            d = e
        self._analysetoken_je_dokument_cache = je_dokument
        return je_dokument

    def docset_word_count(self, doc_ids: Sequence[int]) -> int:
        """Analysis tokens of the documents, the denominator of every word rate."""
        je_dokument = self.analysetoken_je_dokument()
        ids = np.asarray(doc_ids, dtype=np.int64)
        ids = ids[(ids >= 0) & (ids < je_dokument.size)]
        return int(je_dokument[ids].sum()) if ids.size else 0

    def word_count(self) -> int:
        """Analysis tokens of the whole corpus."""
        return int(self.analysetoken_je_dokument().sum())

    def frequency_list_docset(
        self,
        doc_ids: Sequence[int],
        *,
        stopwords: Sequence[str] | None = None,
        pos_prefix: str | None = None,
        attr: str = "word",
        case_fold: bool = True,
    ) -> pl.DataFrame:
        """Return word/lemma/POS frequencies restricted to selected document ids.

        With ``case_fold`` True (the default) surface forms are aggregated by the
        shared ``str.lower`` key (same contract as :meth:`frequency_list`).
        """
        term_ids, counts = self.frequency_counts_docset(
            doc_ids,
            stopwords=stopwords,
            pos_prefix=pos_prefix,
            attr=attr,
            case_fold=case_fold,
        )
        if term_ids.size == 0:
            return pl.DataFrame([], schema=["word", "f"])
        _, lex = self._lexicon_for_frequency_attr(attr)
        if case_fold:
            words = self.casefold_labels(term_ids, attr)
        else:
            words = strings_for_ids(lex.offsets, lex.strings_view, term_ids, True)
        df = pl.DataFrame(
            {
                "word": words,
                "f": counts.astype(np.int64, copy=False),
            }
        )
        if not case_fold:
            return df
        return df.sort("f", descending=True)

    def frequency_counts_docset(
        self,
        doc_ids: Sequence[int],
        *,
        stopwords: Sequence[str] | None = None,
        pos_prefix: str | None = None,
        attr: str = "word",
        case_fold: bool = False,
        variants_out: dict[int, dict[int, int]] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (term_ids, counts) for selected document ids.

        The arrays are sorted by descending count and keep numeric ids so that
        callers can page results without converting all strings eagerly.

        With ``case_fold`` False (the DEFAULT) the result is RAW per-surface-form
        ids and counts — required by the raw-id consumers (the word-sketch
        docset-local f2 lookup and :meth:`frequency_list_docset`'s own internal
        call, which folds the resolved strings itself).

        With ``case_fold`` True the counts are aggregated by ``str.lower``
        class and each class is keyed by its GLOBALLY-STABLE,
        DOCSET-INDEPENDENT representative id (the minimum term_id in the class;
        see :meth:`_casefold_representatives`). This is what the keyness consumers
        request: it makes a ``str.lower`` class (e.g. ``die/Die/DIE``) a single
        keyness candidate with the full per-class frequency, and — because the
        representative is the same id in every docset — keeps the
        ``union1d(target_ids, reference_ids)`` alignment in the
        docset-vs-docset keyness path correct (C-casefold-counting-01).
        """
        attr_norm, lex = self._lexicon_for_frequency_attr(attr)
        if pos_prefix and attr_norm not in {"word", "lemma"}:
            raise ValueError(
                "pos_prefix ist nur für wort- oder lemmabasierte Frequenzen belegt"
            )
        starts, ends, _ = self._doc_ranges_for_ids(doc_ids)
        if starts.size == 0:
            return (
                np.zeros(0, dtype=np.uint32),
                np.zeros(0, dtype=np.uint64),
            )
        seg_weights = np.ones(starts.shape[0], dtype=np.uint32)
        stop_ids: Set[int] | None = None
        if stopwords:
            stop_ids = self._frequency_stop_ids(
                attr_norm,
                lex,
                stopwords,
                case_fold=case_fold,
            )
        counts: dict[int, int] | None = None
        if pos_prefix:
            pos_lex = self.fast_index.lexicons.pos
            if pos_lex is None:
                raise RuntimeError("POS Lexikon fehlt. Bitte Index neu bauen.")
            prefix = str(pos_prefix).strip()
            if prefix:
                allow = np.zeros(pos_lex.vocab_size + 1, dtype=np.uint8)
                pos_ids = np.arange(1, pos_lex.vocab_size + 1, dtype=np.uint32)
                tags = strings_for_ids(
                    pos_lex.offsets, pos_lex.strings_view, pos_ids, True
                )
                for pos_id, tag in zip(pos_ids, tags):
                    if tag.startswith(prefix):
                        allow[int(pos_id)] = 1
                if np.any(allow):
                    counts = count_hashmap_svb_pos(
                        self.fast_index.token_store,
                        starts,
                        ends,
                        seg_weights,
                        allow,
                        stoplist=stop_ids,
                        stream_name=attr_norm,
                    )
                else:
                    # A POS prefix was requested but matched NO pos tag. The
                    # result must be empty -- falling through to the unfiltered
                    # count would mislabel the entire vocabulary as this POS
                    # class (corrupting keyness/contrast).
                    return (
                        np.zeros(0, dtype=np.uint32),
                        np.zeros(0, dtype=np.uint64),
                    )
        if counts is None and attr_norm in {"word", "lemma"}:
            counts = count_hashmap_svb(
                self.fast_index.token_store,
                attr_norm,
                starts,
                ends,
                seg_weights,
                stoplist=stop_ids,
            )
        elif counts is None and attr_norm == "pos":
            pos_ids = self.fast_index.token_store.pos_ids
            max_id = int(lex.vocab_size)
            dense = np.zeros(max_id + 1, dtype=np.int64)
            for start, end in zip(starts.astype(np.int64), ends.astype(np.int64)):
                if end <= start:
                    continue
                slice_ids = np.asarray(pos_ids[int(start) : int(end)], dtype=np.int64)
                slice_ids = slice_ids[(slice_ids > 0) & (slice_ids <= max_id)]
                if stop_ids:
                    slice_ids = slice_ids[~np.isin(slice_ids, list(stop_ids))]
                if slice_ids.size:
                    dense += np.bincount(slice_ids, minlength=max_id + 1).astype(np.int64, copy=False)
            # FIX-C: exclude the index-only ``|LBR|`` sentinel's POS contribution
            # for THESE doc ranges through the shared sentinel seam, so a docset POS
            # frequency matches the canonical figures (e.g. whole-corpus NOUN 9740,
            # VERB 4781) instead of the raw stream count that double-counts |LBR|.
            sentinel_pos = self._sentinel_pos_counts(starts, ends)
            if sentinel_pos.any():
                n = min(dense.size, sentinel_pos.size)
                dense[:n] = np.maximum(dense[:n] - sentinel_pos[:n], 0)
            counts = {int(i): int(v) for i, v in enumerate(dense) if i > 0 and v}
        if not counts:
            return (
                np.zeros(0, dtype=np.uint32),
                np.zeros(0, dtype=np.uint64),
            )
        if case_fold:
            # Aggregate per-surface-form counts into their casefold class, keyed
            # by the globally-stable representative id. Ids absent from the
            # representative map (none in practice — the map covers every lexicon
            # id of the attr) fall back to themselves so no count is dropped.
            rep_map = self._casefold_representatives(attr_norm)
            folded: dict[int, int] = {}
            # The breakdown per surface form is available here and is kept
            # because the reader needs it: the row is labelled with the
            # smallest lexicon id, which in a chronologically built corpus is
            # the first spelling seen. In a parliamentary corpus the row
            # "Beschlußempfehlung" reports 18,656 hits in the 2010s, where this
            # spelling occurs zero times.
            aufschluesselung: dict[int, dict[int, int]] | None = (
                {} if variants_out is not None else None
            )
            for tid, c in counts.items():
                tid_int = int(tid)
                if tid_int <= 0:
                    continue
                rep = rep_map.get(tid_int, tid_int)
                folded[rep] = folded.get(rep, 0) + int(c)
                if aufschluesselung is not None:
                    aufschluesselung.setdefault(rep, {})[tid_int] = int(c)
            if aufschluesselung is not None and variants_out is not None:
                # NICHT "mehr als eine Schreibung". Der gemeldete Fall traegt in
                # den 2010ern GENAU EINE, naemlich Beschlussempfehlung mit 18.656,
                # waehrend die Zeile Beschlussempfehlung heisst. Eine Filterung
                # auf len > 1 haette genau ihn ausgelassen. Aufgeschluesselt wird
                # deshalb, sobald das Etikett nicht die einzige tragende
                # Schreibung ist.
                variants_out.update({
                    rep: teile
                    for rep, teile in aufschluesselung.items()
                    if len(teile) > 1 or rep not in teile
                })
            counts = folded
        term_ids = np.fromiter(
            (int(tid) for tid in counts.keys() if int(tid) > 0),
            dtype=np.uint32,
        )
        if term_ids.size == 0:
            return (
                np.zeros(0, dtype=np.uint32),
                np.zeros(0, dtype=np.uint64),
            )
        freqs = np.fromiter(
            (int(counts[int(tid)]) for tid in term_ids),
            dtype=np.uint64,
        )
        order = np.argsort(freqs)[::-1]
        return term_ids[order], freqs[order]

    # ------------------------------------------------------------------
    # Case-folding (DT-CORE-CASE-FREQ) ---------------------------------
    def _casefold_map(self, attr: str = "word") -> Dict[str, Tuple[int, ...]]:
        """Lazily build (and cache) a ``lowercase -> sorted id tuple`` map.

        One full pass over the lexicon (vocab-sized). The fold uses Python
        ``str.lower``, the SAME contract as CQL ``%c``
        (``cqlhpc.predicates._casefold_match_ids``) and the collocation engine
        (``CollocationEngine._casefold_map``). Keying on the bare lexicon
        string's lowercase (rather than the canonicalized query's) is correct
        because the index already stores NFC/NFKC-normalised surface forms, and
        the query side canonicalizes before folding via
        :func:`candyconc.domain.query_parser.casefold_key`.

        ``str.lower``, not ``str.casefold``: casefold folds ß to ss and would
        put dass, Dass and daß into one class, likewise Maße and Masse, two
        different words. With ``str.lower`` daß stays apart from dass/Dass.
        """
        cached = self._casefold_id_map.get(attr)
        if cached is not None:
            return cached
        with self._casefold_lock:
            cached = self._casefold_id_map.get(attr)
            if cached is not None:
                return cached
            lex = self.fast_index._lexicon_for_attr(attr)
            mapping: Dict[str, list[int]] = {}
            if lex is not None:
                vocab = int(getattr(lex, "vocab_size", 0) or 0)
                get_string = lex.get_string
                for tid in range(1, vocab + 1):
                    s = get_string(tid)
                    if not s:
                        continue
                    mapping.setdefault(s.lower(), []).append(tid)
            frozen: Dict[str, Tuple[int, ...]] = {
                k: tuple(sorted(v)) for k, v in mapping.items()
            }
            self._casefold_id_map[attr] = frozen
            return frozen

    def _casefold_representatives(self, attr: str = "word") -> Dict[int, int]:
        """Lazily build (and cache) a ``term_id -> representative_id`` map.

        The representative of a case class is the MINIMUM term_id in the
        class (``_casefold_map()[key][0]`` — the tuples are sorted ascending).
        This is DOCSET-INDEPENDENT: every member of a class maps to the same id
        no matter which document subset is being counted, so folding the target
        and reference docsets sends a class (e.g. ``{die, Die, DIE}``) to one and
        the same id in both — keeping the ``union1d`` alignment in the
        docset-vs-docset keyness path correct (C-casefold-counting-01). Keying on
        the docset-DOMINANT surface id instead (the reverted attempt) was wrong
        precisely because two docsets can pick different dominant forms for the
        same class and the union then re-splits it.
        """
        cached = self._casefold_rep_map.get(attr)
        if cached is not None:
            return cached
        cf_map = self._casefold_map(attr)
        with self._casefold_lock:
            cached = self._casefold_rep_map.get(attr)
            if cached is not None:
                return cached
            rep: Dict[int, int] = {}
            for ids in cf_map.values():
                if not ids:
                    continue
                representative = int(ids[0])  # min id — sorted ascending
                for tid in ids:
                    rep[int(tid)] = representative
            self._casefold_rep_map[attr] = rep
            return rep

    def _casefold_label_ids(self, attr: str = "word") -> Dict[int, int]:
        """``representative id -> label id`` for folded frequency rows.

        The label of a case class is the spelling with the highest frequency in
        the whole corpus, ties to the smaller id. It is docset-independent like
        the representative, so every scope prints the same label for a class,
        and it is the spelling a reader meets most. The representative (the
        minimum id) is the first spelling the builder saw and can be rare: in
        a corpus of speeches with capitalised title lines the class of "the"
        would be labelled "The".
        """
        cached = self._casefold_label_map.get(attr)
        if cached is not None:
            return cached
        cf_map = self._casefold_map(attr)
        lex = self.fast_index._lexicon_for_attr(attr)
        freqs = lex.get_freqs_array() if lex is not None else np.zeros(0, dtype=np.uint64)
        n_freqs = int(freqs.size)
        labels: Dict[int, int] = {}
        for ids in cf_map.values():
            if not ids:
                continue
            rep = int(ids[0])
            if len(ids) == 1:
                labels[rep] = rep
                continue
            best = rep
            best_f = int(freqs[rep]) if rep < n_freqs else 0
            for tid in ids[1:]:
                f = int(freqs[int(tid)]) if int(tid) < n_freqs else 0
                if f > best_f:
                    best, best_f = int(tid), f
            labels[rep] = best
        self._casefold_label_map[attr] = labels
        return labels

    def casefold_labels(self, rep_ids: Sequence[int], attr: str = "word") -> list[str]:
        """Label strings for folded rows keyed by their representative ids."""
        attr_norm, lex = self._lexicon_for_frequency_attr(attr)
        ids = np.asarray(rep_ids, dtype=np.uint32)
        if ids.size == 0:
            return []
        if attr_norm in {"word", "lemma"}:
            label_map = self._casefold_label_ids(attr_norm)
            ids = np.fromiter(
                (label_map.get(int(t), int(t)) for t in ids), dtype=np.uint32, count=int(ids.size)
            )
        return strings_for_ids(lex.offsets, lex.strings_view, ids, True)

    def _casefold_ids(self, term: str, attr: str = "word") -> np.ndarray:
        """Return all lexicon ids whose lowercase equals ``term``'s lowercase.

        ``term`` is expected to be already canonicalized (the parser/eval layer
        canonicalizes before calling). We fold the canonical form here so the
        equivalence class is exactly the shared ``str.lower`` contract.
        """
        from candyconc.domain.query_parser import canonicalize_term

        canonical = canonicalize_term(term)
        if not canonical:
            return np.zeros(0, dtype=np.uint32)
        ids = self._casefold_map(attr).get(canonical.lower())
        if ids:
            return np.asarray(ids, dtype=np.uint32)
        return np.zeros(0, dtype=np.uint32)

    # ------------------------------------------------------------------
    # Low level lookup helpers -----------------------------------------
    def term_positions(self, term: str, *, case_insensitive: bool = True) -> np.ndarray:
        """Return positions of tokens equal to ``term`` as a uint32 array.

        When ``case_insensitive`` is True (the default, following German plain
        search convention), the match is resolved over the lowercased id-set:
        *every* lexicon type whose ``str.lower`` equals ``term``'s lowercase
        contributes its positions. This unifies plain search with CQL ``%c`` and
        the collocation engine. ``"dass"`` matches Dass and DASS, not ``"daß"``.
        """
        if not case_insensitive:
            return self.fast_index.term_positions(term, attr="word").astype(np.uint32, copy=False)
        ids = self._casefold_ids(term, attr="word")
        if ids.size == 0:
            return np.zeros(0, dtype=np.uint32)
        return self.fast_index._union_positions_for_ids("word", ids).astype(np.uint32, copy=False)

    def _casefold_pattern_ids(self, regex: str, attr: str = "word") -> np.ndarray:
        """Ids whose lowercased surface matches the anchored ``regex`` ignoring case.

        Shared engine for case-insensitive wildcard and regex search. We compile
        the (already anchored) ``regex`` once with ``re.IGNORECASE`` and run it
        against each lowercase key of the case map, the same contract as plain
        ``%c`` search.

        The pattern is not rewritten with ``str.casefold``: that would turn
        "daß*" into "dass.*", which also matches dass and dasselbe, and it
        would turn classes like ``\\W`` into ``\\w``. ``re.IGNORECASE`` leaves
        the pattern as it is and separates ß and ss like ``str.lower``.
        """
        compiled = re.compile(regex, re.IGNORECASE)
        cf_map = self._casefold_map(attr)
        ids: list[int] = []
        for key, key_ids in cf_map.items():
            if compiled.fullmatch(key):
                ids.extend(key_ids)
        if not ids:
            return np.zeros(0, dtype=np.uint32)
        ids.sort()
        return np.asarray(ids, dtype=np.uint32)

    def _positions_for_pattern_ids(
        self, ids: np.ndarray, *, attr: str, limit: int | None, kind: str
    ) -> np.ndarray:
        """Union the positions for resolved casefold-pattern ids, size-capped.

        Mirrors the backend's ``_MAX_REGEX_POSITIONS`` guard (an unbounded CI
        wildcard like ``*`` would otherwise union the whole corpus): estimate the
        result size from the ids' total frequency and refuse runaway patterns.
        """
        if ids.size == 0:
            return np.zeros(0, dtype=np.uint32)
        lex = self.fast_index._lexicon_for_attr(attr)
        if lex is not None:
            try:
                est = int(lex.get_freqs_for_ids(ids).sum())
            except Exception:
                est = 0
            if est > self.fast_index._MAX_REGEX_POSITIONS:
                raise RuntimeError(
                    f"{kind} Treffer zu gross. Bitte Suchmuster einschraenken."
                )
        if limit is not None:
            return self.fast_index._union_positions_for_ids_limited(
                attr, ids, int(limit)
            ).astype(np.uint32, copy=False)
        return self.fast_index._union_positions_for_ids(attr, ids).astype(np.uint32, copy=False)

    def regex_positions(
        self, pattern: str, *, limit: int | None = None, case_insensitive: bool = True
    ) -> np.ndarray:
        """Return positions of tokens matching regex ``pattern`` as a uint32 array.

        When ``case_insensitive`` is True the pattern is matched ignoring case
        against the lowercased lexicon, unifying it with the plain-search /
        ``%c`` contract (``ß`` and ``ss`` stay distinct). When False the backend
        regex path runs verbatim (exact case).
        """
        if not case_insensitive:
            return self.fast_index.regex_positions(pattern, attr="word", limit=limit).astype(
                np.uint32, copy=False
            )
        anchored = pattern if pattern.startswith("^") else f"^{pattern}"
        if not anchored.endswith("$"):
            anchored = f"{anchored}$"
        ids = self._casefold_pattern_ids(anchored, attr="word")
        return self._positions_for_pattern_ids(
            ids, attr="word", limit=limit, kind="Regex"
        )

    def wildcard_positions(
        self, pattern: str, *, limit: int | None = None, case_insensitive: bool = True
    ) -> np.ndarray:
        """Return positions of tokens matching wildcard ``pattern`` as a uint32 array.

        When ``case_insensitive`` is True the wildcard (``*`` -> ``.*``,
        ``?`` -> ``.``) is matched ignoring case against the lowercased lexicon,
        so it shares the plain-search / ``%c`` contract (``ß`` and ``ss`` stay
        distinct). When
        False the backend wildcard path runs verbatim (exact case), so a bare
        wildcard with ``case_insensitive=False`` matches exactly.
        """
        if not case_insensitive:
            return self.fast_index.wildcard_positions(pattern, attr="word", limit=limit).astype(
                np.uint32, copy=False
            )
        regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
        ids = self._casefold_pattern_ids(regex, attr="word")
        return self._positions_for_pattern_ids(
            ids, attr="word", limit=limit, kind="Wildcard"
        )

    def attr_positions(self, key: str, value: str) -> np.ndarray:
        """Return positions for lemma, pos, or morph attributes as a uint32 array."""
        return self.fast_index.attr_positions(key, value).astype(np.uint32, copy=False)

    def entity_positions(self, ent_type: str) -> np.ndarray:
        """Return positions with entity type ``ent_type`` as a uint32 array."""
        return self.fast_index.entity_positions(ent_type).astype(np.uint32, copy=False)

    def rel_positions(self, rel: str) -> np.ndarray:
        """Return positions where dependency relation equals ``rel`` as a uint32 array."""
        return self.fast_index.rel_positions(rel).astype(np.uint32, copy=False)

    def count(self, term: str) -> int:
        """Return total number of hits for ``term``."""
        positions = self.fast_index.term_positions(term, attr="word")
        return int(positions.size)

    def dependency_positions(
        self, rel: str, head_pos: Sequence[int] | None, dep_pos: Sequence[int] | None
    ) -> np.ndarray:
        """Return head positions matching dependency ``rel``."""
        return self.fast_index.dependency_positions(rel, head_pos, dep_pos)

    def dependency_arcs(self, start: int, end: int) -> list[tuple[int, int, str]]:
        """Return dependency arcs within ``start``..``end`` inclusive."""
        return self.fast_index.dependency_arcs(start, end)

    def num_tokens(self) -> int:
        """Return total number of tokens in the index."""
        return self.fast_index.token_store.token_count

    def document_versions(self, path: str) -> list[int]:
        """Return available versions for ``path``."""
        versions: set[int] = set()
        for meta in self.fast_index.doc_metadata.values():
            if not isinstance(meta, dict):
                continue
            if str(meta.get("path") or meta.get("doc_id") or "") != path:
                continue
            try:
                versions.add(int(meta.get("version", 1)))
            except Exception:
                versions.add(1)
        if not versions:
            return []
        return sorted(versions)

    # ------------------------------------------------------------------
    # Context-manager sugar --------------------------------------------
    def __enter__(self) -> "CorpusIndex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
