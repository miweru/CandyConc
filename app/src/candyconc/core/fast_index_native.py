from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import numpy as np

LOGGER = logging.getLogger(__name__)


def _write_build_log_path() -> Path:
    from candyconc.paths import data_dir

    log_dir = data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "fastindex_build.log"


def _write_build_log(path: Path, label: str, stdout: str, stderr: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {label}\n")
        if stdout:
            fh.write("-- stdout --\n")
            fh.write(stdout.rstrip() + "\n")
        if stderr:
            fh.write("-- stderr --\n")
            fh.write(stderr.rstrip() + "\n")
        fh.write("\n")


def _load_fast_index():
    try:
        from ._fast_index import (  # type: ignore
            make_svb_range_decoder,
            kwic_rows_svb,
            kwic_rows_svb_compact_buffers,
            kwic_compact_buffer_rows,
            decode_svb_block,
            decode_svb_range_i32,
            decode_svb_ranges_packed_i32,
            decode_roar_positions,
            roaring_postings_to_bitset,
            bitset_positions_limit,
            union_roar_positions_limited,
            roar_advance_to,
            roar_contains,
            docset_mask_from_ids,
            doc_search_scores,
            dependency_heads,
            lexicon_match_regex,
            lexicon_match_regex_ids,
            lexicon_match_prefix,
            lexicon_match_prefix_ids,
            lexicon_match_suffix,
            lexicon_match_suffix_ids,
            lexicon_match_contains,
            lexicon_match_contains_ids,
            strings_for_ids,
            word_sketch_counts,
            union_sorted,
        )
        return (
            make_svb_range_decoder,
            kwic_rows_svb,
            kwic_rows_svb_compact_buffers,
            kwic_compact_buffer_rows,
            decode_svb_block,
            decode_svb_range_i32,
            decode_svb_ranges_packed_i32,
            decode_roar_positions,
            roaring_postings_to_bitset,
            bitset_positions_limit,
            union_roar_positions_limited,
            roar_advance_to,
            roar_contains,
            docset_mask_from_ids,
            doc_search_scores,
            dependency_heads,
            lexicon_match_regex,
            lexicon_match_regex_ids,
            lexicon_match_prefix,
            lexicon_match_prefix_ids,
            lexicon_match_suffix,
            lexicon_match_suffix_ids,
            lexicon_match_contains,
            lexicon_match_contains_ids,
            strings_for_ids,
            word_sketch_counts,
            union_sorted,
        )
    except Exception as exc:
        log_path = _write_build_log_path()
        raise RuntimeError(
            f"Fast index Extension fehlt. Bitte build_ext ausführen. Log: {log_path}"
        ) from exc


_MAKE_SVB_RANGE_DECODER, _KWIC_ROWS_SVB, _KWIC_ROWS_SVB_COMPACT_BUFFERS, _KWIC_COMPACT_BUFFER_ROWS, _DECODE_SVB_BLOCK, _DECODE_SVB_RANGE_I32, _DECODE_SVB_RANGES_PACKED_I32, _DECODE_ROAR_POSITIONS, _ROARING_POSTINGS_TO_BITSET, _BITSET_POSITIONS_LIMIT, _UNION_ROAR_POSITIONS_LIMITED, _ROAR_ADVANCE_TO, _ROAR_CONTAINS, _DOCSET_MASK_FROM_IDS, _DOC_SEARCH_SCORES, _DEPENDENCY_HEADS, _LEXICON_MATCH_REGEX, _LEXICON_MATCH_REGEX_IDS, _LEXICON_MATCH_PREFIX, _LEXICON_MATCH_PREFIX_IDS, _LEXICON_MATCH_SUFFIX, _LEXICON_MATCH_SUFFIX_IDS, _LEXICON_MATCH_CONTAINS, _LEXICON_MATCH_CONTAINS_IDS, _STRINGS_FOR_IDS, _WORD_SKETCH_COUNTS, _UNION_SORTED = _load_fast_index()

try:
    from . import _fast_index as _fast_index_mod  # type: ignore
    _INTERSECT_SHIFTED = getattr(_fast_index_mod, "intersect_shifted", None)
    _UNION_ROAR_POSITIONS = getattr(_fast_index_mod, "union_roar_positions", None)
except Exception:
    _INTERSECT_SHIFTED = None
    _UNION_ROAR_POSITIONS = None


def kwic_rows_svb(*args, **kwargs):
    if _KWIC_ROWS_SVB is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _KWIC_ROWS_SVB(*args, **kwargs)


def kwic_rows_svb_compact_buffers(*args, **kwargs):
    if _KWIC_ROWS_SVB_COMPACT_BUFFERS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _KWIC_ROWS_SVB_COMPACT_BUFFERS(*args, **kwargs)


def kwic_compact_buffer_rows(*args, **kwargs):
    if _KWIC_COMPACT_BUFFER_ROWS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _KWIC_COMPACT_BUFFER_ROWS(*args, **kwargs)


def make_svb_range_decoder(*args, **kwargs):
    if _MAKE_SVB_RANGE_DECODER is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _MAKE_SVB_RANGE_DECODER(*args, **kwargs)


def decode_svb_block(*args, **kwargs):
    if _DECODE_SVB_BLOCK is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DECODE_SVB_BLOCK(*args, **kwargs)


def decode_svb_range_i32(*args, **kwargs):
    if _DECODE_SVB_RANGE_I32 is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DECODE_SVB_RANGE_I32(*args, **kwargs)


def decode_svb_ranges_packed_i32(*args, **kwargs):
    if _DECODE_SVB_RANGES_PACKED_I32 is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DECODE_SVB_RANGES_PACKED_I32(*args, **kwargs)


def decode_roar_positions(*args, **kwargs):
    if _DECODE_ROAR_POSITIONS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DECODE_ROAR_POSITIONS(*args, **kwargs)


def roaring_postings_to_bitset(*args, **kwargs):
    if _ROARING_POSTINGS_TO_BITSET is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _ROARING_POSTINGS_TO_BITSET(*args, **kwargs)


def bitset_positions_limit(*args, **kwargs):
    if _BITSET_POSITIONS_LIMIT is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _BITSET_POSITIONS_LIMIT(*args, **kwargs)


def union_roar_positions_limited(*args, **kwargs):
    if _UNION_ROAR_POSITIONS_LIMITED is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _UNION_ROAR_POSITIONS_LIMITED(*args, **kwargs)


def roar_advance_to(*args, **kwargs):
    if _ROAR_ADVANCE_TO is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _ROAR_ADVANCE_TO(*args, **kwargs)


def roar_contains(*args, **kwargs):
    if _ROAR_CONTAINS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _ROAR_CONTAINS(*args, **kwargs)


def roaring_ops_available() -> bool:
    return _ROAR_CONTAINS is not None and _ROAR_ADVANCE_TO is not None


def docset_mask_from_ids(*args, **kwargs):
    if _DOCSET_MASK_FROM_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DOCSET_MASK_FROM_IDS(*args, **kwargs)


def doc_search_scores(*args, **kwargs):
    if _DOC_SEARCH_SCORES is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DOC_SEARCH_SCORES(*args, **kwargs)


def dependency_heads(*args, **kwargs):
    if _DEPENDENCY_HEADS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _DEPENDENCY_HEADS(*args, **kwargs)


def lexicon_match_regex(*args, **kwargs):
    if _LEXICON_MATCH_REGEX is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_REGEX(*args, **kwargs)


def lexicon_match_regex_ids(*args, **kwargs):
    if _LEXICON_MATCH_REGEX_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_REGEX_IDS(*args, **kwargs)


def lexicon_match_prefix(*args, **kwargs):
    if _LEXICON_MATCH_PREFIX is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_PREFIX(*args, **kwargs)


def lexicon_match_prefix_ids(*args, **kwargs):
    if _LEXICON_MATCH_PREFIX_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_PREFIX_IDS(*args, **kwargs)


def lexicon_match_suffix(*args, **kwargs):
    if _LEXICON_MATCH_SUFFIX is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_SUFFIX(*args, **kwargs)


def lexicon_match_suffix_ids(*args, **kwargs):
    if _LEXICON_MATCH_SUFFIX_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_SUFFIX_IDS(*args, **kwargs)


def lexicon_match_contains(*args, **kwargs):
    if _LEXICON_MATCH_CONTAINS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_CONTAINS(*args, **kwargs)


def lexicon_match_contains_ids(*args, **kwargs):
    if _LEXICON_MATCH_CONTAINS_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _LEXICON_MATCH_CONTAINS_IDS(*args, **kwargs)


def strings_for_ids(*args, **kwargs):
    if _STRINGS_FOR_IDS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _STRINGS_FOR_IDS(*args, **kwargs)


def word_sketch_counts(*args, **kwargs):
    if _WORD_SKETCH_COUNTS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _WORD_SKETCH_COUNTS(*args, **kwargs)


def union_sorted(*args, **kwargs):
    if _UNION_SORTED is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _UNION_SORTED(*args, **kwargs)


def intersect_shifted(a, b, shift: int, max_pos: int):
    if _INTERSECT_SHIFTED is not None:
        return _INTERSECT_SHIFTED(a, b, int(shift), int(max_pos))
    # Python fallback: create shifted view and intersect.
    if b.size == 0 or a.size == 0:
        return np.zeros(0, dtype=np.uint32)
    shifted = b.astype(np.int64) - int(shift)
    shifted = shifted[(shifted >= 0) & (shifted <= int(max_pos))]
    if shifted.size == 0:
        return np.zeros(0, dtype=np.uint32)
    return np.intersect1d(a, shifted.astype(np.uint32, copy=False), assume_unique=True)


def union_roar_positions(offsets, data, ids):
    if _UNION_ROAR_POSITIONS is None:
        log_path = _write_build_log_path()
        raise RuntimeError(f"Fast index Extension fehlt. Details: {log_path}")
    return _UNION_ROAR_POSITIONS(offsets, data, ids)
