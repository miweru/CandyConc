"""Bilingual texts of the server core and its services.

Error answers of the real app come in the language of the request
(``Accept-Language``) and stay German without one. Service objects that are
read later (analysis jobs, operation runs, the persisted status of a local
semantic-index build) keep their texts as pairs and render them in the
language of the request that reads them.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candyconc.entrypoints.errors import register_exception_handlers
from candyconc.i18n import LocalizedText, exception_text, language_scope, lt
from candyconc.services import llm_client
from candyconc.services import semantic_index_jobs
from candyconc.services.backend import analysis_jobs, server
from candyconc.services.backend.operation_runs import OperationRunRegistry
from candyconc.services.backend.request_language import LanguageMiddleware

EN = {"Accept-Language": "en, de;q=0.5"}
DE = {"Accept-Language": "de, en;q=0.5"}
TOOLS = Path(__file__).resolve().parents[2] / "src" / "candyconc" / "tools"


def _client() -> TestClient:
    return TestClient(server.app, raise_server_exceptions=False)


# --- error answers of the real app ------------------------------------------


def test_unsupported_media_type_in_both_languages():
    client = _client()
    plain = {"Content-Type": "text/plain"}
    en = client.post("/api/v1/chat", content=b"hello", headers={**plain, **EN})
    de = client.post("/api/v1/chat", content=b"hello", headers=plain)
    assert en.status_code == de.status_code == 415
    assert en.json()["detail"] == "Unsupported Media Type: expected 'application/json'. Received: text/plain."
    assert de.json()["detail"] == "Unsupported Media Type: erwartet wird 'application/json'. Empfangen: text/plain."
    assert en.json()["code"] == de.json()["code"] == "request.unsupported_media_type"
    assert en.json()["params"] == {"content_type": "text/plain"}


def test_negative_offset_in_both_languages(monkeypatch):
    monkeypatch.setattr(server, "get_corpus", lambda _name: object())
    client = _client()
    en = client.get("/api/v1/query", params={"term": "the", "offset": -3}, headers=EN)
    de = client.get("/api/v1/query", params={"term": "the", "offset": -3})
    assert en.status_code == de.status_code == 422, de.text
    assert en.json()["detail"] == "offset must be >= 0 (received: -3)"
    assert de.json()["detail"] == "offset muss >= 0 sein (erhalten: -3)"
    assert en.json()["code"] == "request.offset_negative"
    assert en.json()["params"] == {"value": -3}


def test_ngram_bounds_in_both_languages():
    client = _client()
    body = {"min_n": 0, "max_n": 2}
    en = client.post("/api/v1/analysis/ngrams", json=body, headers=EN)
    de = client.post("/api/v1/analysis/ngrams", json=body, headers=DE)
    assert en.status_code == de.status_code == 400, de.text
    assert en.json()["detail"] == "min_n and max_n must be >= 1"
    assert de.json()["detail"] == "min_n und max_n müssen >= 1 sein"
    assert en.json()["code"] == "ngram.bounds_invalid"


def test_chat_shape_errors_in_both_languages():
    client = _client()
    en = client.post("/api/v1/chat", json={"message": "hi"}, headers=EN)
    de = client.post("/api/v1/chat", json={"message": "hi"})
    assert en.status_code == de.status_code == 422, de.text
    assert en.json()["detail"].startswith("Unknown field 'message' (singular). Expected a non-empty")
    assert en.json()["detail"].endswith('{"messages": [{"role": "user", "content": "..."}]}.')
    assert de.json()["detail"] == (
        "Unbekanntes Feld 'message' (Singular). Erwartet wird ein nicht-leeres "
        "'messages'-Array, dessen letzter Eintrag eine User-Nachricht mit "
        "nicht-leerem 'content' ist, z.B. "
        '{"messages": [{"role": "user", "content": "..."}]}.'
    )
    last = {"messages": [{"role": "assistant", "content": "x"}]}
    assert client.post("/api/v1/chat", json=last, headers=EN).json()["detail"] == (
        "The last 'messages' entry must be a user message (role='user')."
    )


def test_exception_detail_keeps_the_pair_of_an_index_error(monkeypatch):
    def broken_index():
        raise RuntimeError(server._INDEX_PATH_MISSING.format(path="/nowhere"))

    monkeypatch.setattr(server, "get_index", broken_index)
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(LanguageMiddleware)

    @app.get("/default")
    def _default() -> dict:
        server.get_corpus(None)
        return {}

    client = TestClient(app)
    assert client.get("/default", headers=EN).json()["detail"] == "Index path does not exist: /nowhere"
    assert client.get("/default").json()["detail"] == "Indexpfad existiert nicht: /nowhere"


# --- copilot errors from the LLM client -------------------------------------


def _status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://example.invalid/v1/responses")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("failed", request=request, response=response)


def test_llm_error_message_is_a_pair_and_reaches_the_answer_in_both_languages():
    error = llm_client._classify_http_error("http://example.invalid/v1/responses", _status_error(401))
    assert error.kind == llm_client.LLMErrorKind.AUTH_FAILED
    assert error.message == "Der LLM-Endpunkt hat die Anfrage nicht akzeptiert. Prüfe Schlüssel und Berechtigungen."
    assert error.message.en == "The LLM endpoint did not accept the request. Check the key and permissions."
    assert str(error) == error.message
    assert exception_text(error).en == error.message.en

    overloaded = llm_client._classify_http_error("http://example.invalid/v1/responses", _status_error(503))
    assert overloaded.message.en == "The LLM endpoint is currently overloaded (503)."

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(LanguageMiddleware)

    @app.post("/chat")
    def _chat() -> dict:
        server._raise_llm_http_error(error)
        return {}

    client = TestClient(app)
    en = client.post("/chat", headers=EN).json()["detail"]
    de = client.post("/chat").json()["detail"]
    assert en == {"code": "auth_failed", "message": error.message.en}
    assert de == {"code": "auth_failed", "message": str.__str__(error.message)}


def test_llm_transport_error_keeps_the_technical_part_in_both_languages():
    error = llm_client._classify_transport_error("http://x", httpx.ConnectError("refused"))
    assert error.message == "Transportfehler beim LLM-Endpunkt: refused"
    assert error.message.en == "Transport error at the LLM endpoint: refused"


# --- analysis jobs ----------------------------------------------------------


def test_analysis_job_progress_and_error_follow_the_reading_request():
    job = analysis_jobs.create("frequency_list", "sotu_en", {})
    analysis_jobs.update(
        job.job_id, progress=15, message=lt("Tokenfrequenzen werden gezählt", "Counting token frequencies")
    )
    assert analysis_jobs.snapshot(job.job_id)["message"] == "Tokenfrequenzen werden gezählt"
    with language_scope("en"):
        assert analysis_jobs.snapshot(job.job_id)["message"] == "Counting token frequencies"

    analysis_jobs.set_error(job.job_id, RuntimeError(server._WORD_LEXICON_MISSING))
    with language_scope("en"):
        snap = analysis_jobs.snapshot(job.job_id)
    assert snap["error"] == "Word lexicon is missing. Rebuild the index."
    assert snap["message"] == "error: Word lexicon is missing. Rebuild the index."
    assert analysis_jobs.snapshot(job.job_id)["error"] == "Word Lexikon fehlt. Bitte Index neu bauen."
    # A snapshot is plain JSON data in one language.
    json.dumps(analysis_jobs.snapshot(job.job_id))


def test_analysis_job_stream_renders_in_the_language_of_the_subscriber():
    job = analysis_jobs.create("ngrams", "sotu_en", {})

    async def collect() -> list[dict]:
        seen: list[dict] = []

        async def consume() -> None:
            with language_scope("en"):
                async for item in analysis_jobs.stream(job.job_id):
                    seen.append(item)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        analysis_jobs.update(
            job.job_id, progress=70, message=lt("Ngram Ergebnisse werden sortiert", "Sorting n-gram results")
        )
        await asyncio.sleep(0)
        analysis_jobs.set_result(job.job_id, result={"rows": []}, total_rows=0)
        await asyncio.wait_for(task, 5)
        return seen

    seen = asyncio.run(collect())
    assert "Sorting n-gram results" in [item["message"] for item in seen]
    assert all(not isinstance(item["message"], LocalizedText) for item in seen)


def test_job_task_end_keeps_the_last_message_in_both_languages():
    job = analysis_jobs.create("keyness_docset", "sotu_en", {})
    analysis_jobs.update(job.job_id, progress=20, message=lt("Zähler werden ausgerichtet", "Aligning counts"))

    class _Cancelled:
        def cancelled(self) -> bool:
            return True

    analysis_jobs._task_endete(job.job_id, _Cancelled())
    assert analysis_jobs.get(job.job_id).error == (
        "Der Job-Task wurde abgebrochen. Zuletzt: progress=20 message='Zähler werden ausgerichtet'"
    )
    with language_scope("en"):
        assert analysis_jobs.snapshot(job.job_id)["error"] == (
            "The job task was cancelled. Last state: progress=20 message='Aligning counts'"
        )


# --- operation runs ---------------------------------------------------------


def test_operation_run_defaults_render_in_the_request_language():
    registry = OperationRunRegistry()
    run = registry.create(operation_id="op", source_id="src")
    assert run.to_dict()["message"] == "Operation wurde eingereiht."
    with language_scope("en"):
        assert run.to_dict()["message"] == "Operation queued."
    registry.mark_stale(run.run_id)
    with language_scope("en"):
        data = run.to_dict()
    assert data["error"] == data["warnings"][0] == "Operation status is no longer reliable."


# --- local semantic-index build ---------------------------------------------


def test_persisted_build_status_is_shown_in_the_request_language(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDYCONC_SEMANTIC_JOB_DIR", str(tmp_path))
    run_id = "a" * 32
    state = {
        "schema_version": semantic_index_jobs.STATE_SCHEMA,
        "run_id": run_id,
        "corpus": "sotu_en",
        "status": "failed",
        "progress": 40,
        # written by tools/semantic_index_build.py as plain German text
        "message": "Semantik-Build fehlgeschlagen: MLX-Worker endete mit Code 3",
        "error": "MLX-Worker endete mit Code 3",
        "warnings": ["Der lokale MLX-Build ist nur auf Apple-Silicon-Macs verfügbar."],
    }
    (tmp_path / run_id).mkdir()
    (tmp_path / run_id / "state.json").write_text(json.dumps(state), encoding="utf-8")

    client = _client()
    token = client.post("/api/v1/login", json={"username": "alice", "password": "alice"}).json()["token"]
    admin = {"Authorization": f"Bearer {token}"}
    url = f"/api/v1/embeddings/local-index/builds/{run_id}"
    en = client.get(url, headers={**admin, **EN})
    assert en.status_code == 200, en.text
    snap = en.json()
    assert snap["label"] == "Semantic index: sotu_en"
    assert snap["message"] == "Semantic index build failed: MLX worker exited with code 3"
    assert snap["error"] == "MLX worker exited with code 3"
    assert snap["warnings"] == ["The local MLX build is only available on Apple silicon Macs."]

    german = client.get(url, headers=admin).json()
    assert german["label"] == "Semantischer Index: sotu_en"
    assert german["message"] == state["message"]
    assert german["warnings"] == state["warnings"]


def test_status_text_reads_both_languages_and_passes_unknown_text():
    text = semantic_index_jobs.status_text("Korpustexte werden rekonstruiert (1,000/20,000).")
    assert text.en == "Reconstructing corpus texts (1,000/20,000)."
    back = semantic_index_jobs.status_text("Reconstructing corpus texts (1,000/20,000).")
    assert str.__str__(back) == "Korpustexte werden rekonstruiert (1,000/20,000)."
    assert semantic_index_jobs.status_text("free text") == "free text"
    assert semantic_index_jobs.status_text(None) is None


def _sample_text(node: ast.AST) -> str | None:
    """The written text with every formatted value replaced by a sample."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "7"
            for part in node.values
        )
    return None


def _written_texts(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "_update_state":
            for keyword in node.keywords:
                if keyword.arg == "message":
                    text = _sample_text(keyword.value)
                    if text:
                        found.append((node.lineno, text))
        if name == "RuntimeError" and path.name == "semantic_index_build.py" and node.args:
            text = _sample_text(node.args[0])
            if text:
                found.append((node.lineno, text))
    return found


def test_every_text_the_build_process_writes_has_a_pair():
    missing = []
    for name in ("semantic_index_build.py", "semantic_mlx_worker.py"):
        texts = _written_texts(TOOLS / name)
        assert texts, name
        for line, text in texts:
            if not isinstance(semantic_index_jobs.status_text(text), LocalizedText):
                missing.append(f"{name}:{line}: {text}")
    assert missing == []
