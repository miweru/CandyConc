"""QW3 / R3.12: RejectSink per-row reject & coverage reporting.

The sink is opt-in: every existing call site defaults reject_sink=None and keeps
the silent-continue / RuntimeError behaviour exactly. These tests pin the sink's
counting, reason codes, sampling and fatal-policy behaviour, and confirm the
no-sink path is unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.jobs.build_fast_index_from_parquet import (  # noqa: E402
    _build_doc_stream,
    _build_generic_doc_stream,
    RejectSink,
    RejectError,
)


def _doc_stream(rows, sink, **kw):
    return list(_build_doc_stream(
        rows, include_prompts=False, split_long_texts=False,
        max_doc_chars=0, require_input_text=kw.get("require_input_text", False),
        reject_sink=sink,
    ))


def test_empty_target_text_counted():
    rows = [{"source": "news", "doc_id": "d1", "variant": "original",
             "model": "human", "text_type": "human"}]
    sink = RejectSink()
    out = _doc_stream(rows, sink)
    assert out == []
    assert sink.rows_seen == 1
    assert sink.rows_rejected == 1
    assert sink.summary()["by_reason"] == {"empty_target_text": 1}


def test_no_ref_text_counted():
    rows = [{"source": "news", "doc_id": "d2", "variant": "rewrite",
             "model": "gpt", "text_type": "ai", "target_text": "Antwort."}]
    sink = RejectSink()
    out = _doc_stream(rows, sink)
    assert out == []
    assert sink.summary()["by_reason"]["no_ref_text"] == 1


def test_thinking_only_counted():
    rows = [{"source": "news", "doc_id": "d3", "variant": "rewrite",
             "model": "gpt", "text_type": "ai", "input_text": "Quelle.",
             "target_text": "<thinking>Nur Denken.</thinking>"}]
    sink = RejectSink()
    _doc_stream(rows, sink)
    assert sink.summary()["by_reason"].get("thinking_only_output", 0) == 1


def test_fail_fast_raises_reject_error():
    rows = [{"source": "news", "doc_id": "d4", "variant": "rewrite",
             "model": "gpt", "text_type": "ai", "input_text": "",
             "target_text": "X."}]
    sink = RejectSink(error_policy="fail_fast")
    with pytest.raises(RejectError):
        _doc_stream(rows, sink, require_input_text=True)


def test_require_input_text_without_sink_still_raises_runtime_error():
    rows = [{"source": "news", "doc_id": "d5", "variant": "rewrite",
             "model": "gpt", "text_type": "ai", "target_text": "X."}]
    with pytest.raises(RuntimeError, match="input_text fehlt"):
        list(_build_doc_stream(
            rows, include_prompts=False, split_long_texts=False,
            max_doc_chars=0, require_input_text=True))


def test_missing_input_text_fatal_with_sink():
    rows = [{"source": "news", "doc_id": "d6", "variant": "rewrite",
             "model": "gpt", "text_type": "ai", "target_text": "X."}]
    sink = RejectSink()
    with pytest.raises(RejectError):
        _doc_stream(rows, sink, require_input_text=True)
    assert sink.summary()["by_reason"]["missing_input_text"] == 1


def test_no_alignment_anchor_fatal_with_sink():
    # AI row with target_text but no doc_id / pair_id / reference_text / source_text /
    # origin_id -> no alignment anchor -> fatal reject (and RuntimeError without sink).
    rows = [{"source": "news", "variant": "rewrite", "model": "gpt",
             "text_type": "ai", "target_text": "Antwort ohne Anker."}]
    sink = RejectSink()
    with pytest.raises(RejectError):
        _doc_stream(rows, sink)
    assert sink.summary()["by_reason"]["no_alignment_anchor"] == 1


def test_no_alignment_anchor_without_sink_raises_runtime_error():
    rows = [{"source": "news", "variant": "rewrite", "model": "gpt",
             "text_type": "ai", "target_text": "Antwort ohne Anker."}]
    with pytest.raises(RuntimeError, match="Alignment Anker"):
        list(_build_doc_stream(
            rows, include_prompts=False, split_long_texts=False,
            max_doc_chars=0, require_input_text=False))


def test_generic_stream_empty_text_counted():
    rows = [{"text": "", "doc_id": "g1"}]
    sink = RejectSink()
    out = list(_build_generic_doc_stream(
        rows, text_column="text", id_column="doc_id", reject_sink=sink))
    assert out == []
    assert sink.summary()["by_reason"] == {"empty_text_column": 1}


def test_summary_counts_and_rate():
    rows = [
        {"source": "news", "doc_id": "h", "variant": "original",
         "model": "human", "text_type": "human", "target_text": "Gültig eins."},
        {"source": "news", "doc_id": "x1", "variant": "original",
         "model": "human", "text_type": "human"},  # empty target
        {"source": "news", "doc_id": "x2", "variant": "original",
         "model": "human", "text_type": "human"},  # empty target
    ]
    sink = RejectSink()
    out = _doc_stream(rows, sink)
    assert len(out) == 1
    s = sink.summary()
    assert s["rows_seen"] == 3
    assert s["rows_rejected"] == 2
    assert s["rejection_rate"] == round(2 / 3, 6)


def test_max_sample_cap():
    rows = [{"source": "news", "doc_id": f"d{i}", "variant": "original",
             "model": "human", "text_type": "human"} for i in range(60)]
    sink = RejectSink()
    _doc_stream(rows, sink)
    assert sink.rows_rejected == 60
    assert len(sink.summary()["samples"]) == 50  # default max_sample


def test_flush_writes_reject_report_json(tmp_path):
    sink = RejectSink()
    sink.record(1, "empty_target_text", {"doc_id": "d"})
    sink.flush(tmp_path)
    report = tmp_path / "reject_report.json"
    assert report.exists()
    import json
    data = json.loads(report.read_text())
    assert data["rows_rejected"] == 1
    assert data["by_reason"] == {"empty_target_text": 1}


def test_rows_seen_includes_dropped_rows():
    rows = [
        {"source": "news", "doc_id": "h", "variant": "original",
         "model": "human", "text_type": "human", "target_text": "Ok."},
        {"source": "news", "doc_id": "x", "variant": "original",
         "model": "human", "text_type": "human"},
        {"source": "news", "doc_id": "y", "variant": "original",
         "model": "human", "text_type": "human"},
    ]
    sink = RejectSink()
    _doc_stream(rows, sink)
    assert sink.rows_seen == 3


def test_log_path_writes_jsonl(tmp_path):
    log = tmp_path / "rejects.jsonl"
    sink = RejectSink(log_path=log)
    sink.open_log()
    sink.record(1, "empty_target_text", {"doc_id": "a"})
    sink.record(2, "no_ref_text", {"doc_id": "b"})
    sink.close_log()
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    import json
    assert json.loads(lines[0])["reason"] == "empty_target_text"
