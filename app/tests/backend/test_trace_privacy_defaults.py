from pathlib import Path

import candyconc.config as cc_config
from candyconc.services.backend import trace


def _reset_trace(
    monkeypatch,
    tmp_path,
    *,
    mode: str,
    enabled: bool | None = None,
    debug_messages: bool = False,
) -> Path:
    traces_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(trace, "_TRACES_PATH", traces_path)
    monkeypatch.setattr(cc_config.APP_CONFIG, "CANDYCONC_SECURITY_MODE", mode)
    monkeypatch.setattr(cc_config.APP_CONFIG, "CANDYCONC_ENABLE_LLM_TRACE", enabled)
    monkeypatch.delenv("CANDYCONC_LLM_TRACE_DEBUG", raising=False)
    monkeypatch.delenv("CANDYCONC_LLM_TRACE_DEBUG_MESSAGES", raising=False)
    if debug_messages:
        monkeypatch.setenv("CANDYCONC_LLM_TRACE_DEBUG_MESSAGES", "1")
    return traces_path


def test_llm_trace_disabled_by_default_in_release(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="release", enabled=None)

    trace_id = trace.record_pre([{"role": "user", "content": "secret"}], [], "alice", "model")
    trace.record_post(trace_id, tokens=0)

    assert trace_id == ""
    assert not traces_path.exists()


def test_llm_trace_disabled_by_default_in_production_alias(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="production", enabled=None)

    trace_id = trace.record_pre([{"role": "user", "content": "secret"}], [], "alice", "model")

    assert trace_id == ""
    assert not traces_path.exists()


def test_llm_trace_still_enabled_by_default_in_local_dev(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="local_dev_unsafe", enabled=None)

    trace_id = trace.record_pre([{"role": "user", "content": "debug"}], [], "alice", "model")
    trace.record_post(trace_id, tokens=0)

    assert trace_id
    assert traces_path.exists()
    text = traces_path.read_text("utf-8")
    assert "debug" not in text
    assert "[redacted]" in text


def test_llm_trace_can_be_explicitly_enabled_in_release(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="release", enabled=True)

    trace_id = trace.record_pre([{"role": "user", "content": "debug"}], [], "alice", "model")

    assert trace_id
    assert traces_path.exists()


def test_trace_storage_keeps_raw_messages_only_in_debug_mode(tmp_path, monkeypatch):
    traces_path = _reset_trace(
        monkeypatch,
        tmp_path,
        mode="release",
        enabled=True,
        debug_messages=True,
    )

    trace_id = trace.record_pre(
        [{"role": "user", "content": "raw-debug-secret"}],
        [],
        "alice",
        "model",
    )

    assert trace_id
    assert "raw-debug-secret" in traces_path.read_text("utf-8")


def test_trace_query_redacts_legacy_raw_messages_by_default(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="release", enabled=True)
    traces_path.write_text(
        '{"id":"legacy","event":"pre","ts":"2026-01-01T00:00:00",'
        '"user":"alice","model":"model","messages":[{"role":"user",'
        '"content":"legacy-secret"}],"tools":[]}\n',
        encoding="utf-8",
    )

    rows = trace.query()

    assert rows[0]["messages"][0]["content"] == "[redacted]"
    assert rows[0]["messages_redacted"] is True
    assert "legacy-secret" not in str(rows)


def test_trace_query_requires_debug_mode_for_raw_admin_output(tmp_path, monkeypatch):
    _reset_trace(
        monkeypatch,
        tmp_path,
        mode="release",
        enabled=True,
        debug_messages=True,
    )
    trace.record_pre(
        [{"role": "user", "content": "admin-debug-secret"}],
        [],
        "alice",
        "model",
    )

    default_rows = trace.query(include_raw_messages=False)
    raw_rows = trace.query(include_raw_messages=True)

    assert default_rows[0]["messages"][0]["content"] == "[redacted]"
    assert raw_rows[0]["messages"][0]["content"] == "admin-debug-secret"


def test_trace_record_stores_tool_names_only(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="local_dev_unsafe", enabled=True)

    trace.record_pre(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "run_cqp_query", "parameters": {"x": 1}}}],
        "alice",
        "model",
    )

    row = __import__("json").loads(traces_path.read_text("utf-8").splitlines()[0])
    assert row["tools"] == ["run_cqp_query"]
    assert "parameters" not in str(row["tools"])


def test_trace_append_rotates_oversized_file(tmp_path, monkeypatch):
    traces_path = _reset_trace(monkeypatch, tmp_path, mode="local_dev_unsafe", enabled=True)
    monkeypatch.setattr(trace, "_TRACES_MAX_BYTES", 64)
    traces_path.write_text("x" * 128 + "\n", encoding="utf-8")

    trace_id = trace.record_pre([{"role": "user", "content": "hi"}], [], "alice", "model")

    assert trace_id
    rotated = traces_path.with_name(traces_path.name + ".1")
    assert rotated.exists()
    assert rotated.read_text("utf-8").startswith("x" * 64)
    assert trace_id in traces_path.read_text("utf-8")
