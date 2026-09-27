"""Bilingual server texts: LocalizedText, ApiError and the request language.

German stays the default: a request without a supported Accept-Language gets
the German text, exactly as before. With ``Accept-Language: en`` the same
response carries the English text. Error answers keep ``detail`` (in the
request language) and add a stable ``code`` with ``params``.
"""

from __future__ import annotations

import ast
import copy
import json
import pickle
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.testclient import TestClient

from candyconc.entrypoints.errors import ApiError, register_exception_handlers
from candyconc.i18n import (
    LocalizedText,
    bilingual_form,
    current_language,
    exception_text,
    join_texts,
    language_scope,
    localize,
    lt,
    placeholders,
)
from candyconc.services.backend.request_language import LanguageMiddleware

SRC = Path(__file__).resolve().parents[2] / "src" / "candyconc"
EN = {"Accept-Language": "en, de;q=0.5"}
DE = {"Accept-Language": "de, en;q=0.5"}


# --- LocalizedText ------------------------------------------------------------


def test_localized_text_is_the_german_string():
    text = lt("Korpus nicht gefunden", "Corpus not found")
    assert text == "Korpus nicht gefunden"
    assert isinstance(text, str)
    assert json.dumps({"m": text}, ensure_ascii=False) == '{"m": "Korpus nicht gefunden"}'
    assert text.resolve("en") == "Corpus not found"
    assert text.resolve("de") == "Korpus nicht gefunden"
    assert text.resolve("fr") == "Korpus nicht gefunden"
    assert type(text.resolve("en")) is str


def test_format_and_concatenation_keep_both_languages():
    unit = lt("Einträge", "entries")
    text = lt("{n} {unit} in {corpus}", "{n} {unit} in {corpus}").format(
        n=3, unit=unit, corpus="sotu_en"
    )
    assert text == "3 Einträge in sotu_en"
    assert text.en == "3 entries in sotu_en"
    joined = lt("Frequenz", "Frequency") + ": " + lt("hoch", "high")
    assert joined.en == "Frequency: high"
    assert ("> " + lt("Treffer", "hits")).en == "> hits"
    both = join_texts(", ", [lt("eins", "one"), "2", lt("drei", "three")])
    assert both == "eins, 2, drei" and both.en == "one, 2, three"


def test_copy_and_pickle_keep_the_english_text():
    text = lt("Wortform", "Word form")
    for clone in (copy.copy(text), copy.deepcopy(text), pickle.loads(pickle.dumps(text))):
        assert isinstance(clone, LocalizedText)
        assert clone.en == "Word form"
    payload = copy.deepcopy({"features": [{"label": text}]})
    assert payload["features"][0]["label"].en == "Word form"


def test_localize_walks_containers_and_uses_the_current_language():
    payload = {"label": lt("Wortform", "Word form"), "rows": [(1, lt("ja", "yes"))], "n": 2}
    assert localize(payload, "en") == {"label": "Word form", "rows": [(1, "yes")], "n": 2}
    assert localize(payload) == {"label": "Wortform", "rows": [(1, "ja")], "n": 2}
    with language_scope("en"):
        assert current_language() == "en"
        assert localize(payload)["label"] == "Word form"
    assert current_language() == "de"
    assert bilingual_form(payload)["label"] == {"de": "Wortform", "en": "Word form"}


def test_exception_text_keeps_the_pair_of_a_raised_message():
    exc = ValueError(lt("Ungültige Zahl", "Invalid number"))
    assert str(exc) == "Ungültige Zahl"
    assert exception_text(exc).en == "Invalid number"
    assert exception_text(ValueError("plain")) == "plain"


# --- problem+json -------------------------------------------------------------


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(LanguageMiddleware)

    @app.get("/corpus/{name}")
    async def _corpus(name: str) -> dict:
        raise ApiError(
            404,
            "corpus.not_found",
            lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"),
            name=name,
        )

    @app.get("/plain")
    async def _plain() -> dict:
        raise HTTPException(status_code=400, detail=lt("Bitte einen Suchbegriff eingeben.", "Please enter a search term."))

    @app.get("/legacy")
    async def _legacy() -> dict:
        raise HTTPException(status_code=409, detail="unverändert")

    @app.get("/needs-term")
    async def _needs_term(term: str = Query(...)) -> dict:  # noqa: B008
        return {"term": term}

    @app.get("/crash")
    async def _crash() -> dict:
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def test_api_error_detail_follows_the_request_language():
    client = _client()
    en = client.get("/corpus/sotu", headers=EN)
    de = client.get("/corpus/sotu", headers=DE)
    default = client.get("/corpus/sotu")
    assert en.status_code == de.status_code == default.status_code == 404
    assert en.headers["content-type"].startswith("application/problem+json")
    assert en.json()["detail"] == "Corpus not found: sotu"
    assert de.json()["detail"] == "Korpus nicht gefunden: sotu"
    assert default.json()["detail"] == "Korpus nicht gefunden: sotu"
    for body in (en.json(), de.json()):
        assert body["code"] == "corpus.not_found"
        assert body["params"] == {"name": "sotu"}
        assert body["status"] == 404
        assert body["title"] == "Not Found"


def test_api_error_detail_is_german_for_code_that_reads_it():
    exc = ApiError(404, "corpus.not_found", lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"), name="x")
    assert exc.detail == "Korpus nicht gefunden: x"
    assert exc.detail.en == "Corpus not found: x"
    assert exc.code == "corpus.not_found" and exc.params == {"name": "x"}


def test_plain_http_exceptions_resolve_and_legacy_details_stay():
    client = _client()
    assert client.get("/plain", headers=EN).json()["detail"] == "Please enter a search term."
    assert client.get("/plain").json()["detail"] == "Bitte einen Suchbegriff eingeben."
    legacy = client.get("/legacy", headers=EN).json()
    assert legacy["detail"] == "unverändert"
    assert "code" not in legacy


def test_validation_and_internal_errors_are_bilingual():
    client = _client()
    en = client.get("/needs-term", headers=EN).json()
    de = client.get("/needs-term").json()
    assert en["detail"] == "Request validation failed: 1 error"
    assert de["detail"] == "Anfrage ungültig: 1 Fehler"
    assert en["code"] == de["code"] == "request.validation_failed"
    assert en["errors"] and de["errors"]
    crash_en = client.get("/crash", headers=EN)
    assert crash_en.status_code == 500
    assert crash_en.json()["detail"] == "Internal server error"
    assert client.get("/crash").json()["detail"] == "Interner Serverfehler"


def test_routes_with_a_response_model_are_localized_before_serialization():
    # FastAPI serializes a route with a response model (also one inferred from
    # ``-> dict[str, Any]``) through pydantic, which would flatten every pair
    # to German. CandyAPIRouter routes localize the result first.
    from typing import Any

    from pydantic import BaseModel

    from candyconc.entrypoints.errors import CandyAPIRouter

    class Label(BaseModel):
        label: str

    router = CandyAPIRouter()

    @router.get("/annotated")
    async def _annotated() -> dict[str, Any]:
        return {"label": lt("Wortform", "Word form")}

    @router.get("/sync")
    def _sync() -> dict[str, Any]:
        return {"label": lt("Wortform", "Word form")}

    @router.get("/model", response_model=Label)
    async def _model() -> dict[str, Any]:
        return {"label": lt("Wortform", "Word form")}

    @router.get("/plain")
    async def _plain():
        return {"label": lt("Wortform", "Word form")}

    app = FastAPI()
    app.add_middleware(LanguageMiddleware)
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    for path in ("/api/annotated", "/api/sync", "/api/model"):
        assert client.get(path, headers=EN).json() == {"label": "Word form"}, path
        assert client.get(path).json() == {"label": "Wortform"}, path
    # Without a response model the pair reaches the response class unchanged.
    assert client.get("/api/plain").json() == {"label": "Wortform"}


def test_websocket_language_comes_from_the_query_parameter():
    app = FastAPI()
    app.add_middleware(LanguageMiddleware)

    @app.websocket("/ws")
    async def _ws(websocket: WebSocket) -> None:
        from candyconc.services.backend.request_language import request_language

        await websocket.accept()
        await websocket.send_json({"current": current_language(), "request": request_language(websocket)})
        await websocket.close()

    client = TestClient(app)
    with client.websocket_connect("/ws?ticket=t&lang=en", headers={"Accept-Language": "de"}) as ws:
        assert ws.receive_json() == {"current": "en", "request": "en"}
    with client.websocket_connect("/ws", headers={"Accept-Language": "en"}) as ws:
        assert ws.receive_json() == {"current": "en", "request": "en"}
    with client.websocket_connect("/ws?lang=fr") as ws:
        assert ws.receive_json() == {"current": "de", "request": "de"}


def test_backend_json_response_resolves_texts_in_the_request_language():
    from candyconc.services.backend.server import _SafeJSONResponse

    body = {"label": lt("Wortform", "Word form"), "values": [float("nan"), lt("ja", "yes")]}
    with language_scope("en"):
        assert json.loads(_SafeJSONResponse(body).body) == {"label": "Word form", "values": [None, "yes"]}
    assert json.loads(_SafeJSONResponse(body).body) == {"label": "Wortform", "values": [None, "ja"]}


# --- catalogue consistency ----------------------------------------------------

_CODE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
# A German word (three or more letters with an umlaut or sharp s) in an
# English text points to swapped or untranslated arguments. A quoted single
# character such as "ß" is allowed.
_GERMAN_WORD = re.compile(r"\b\w*[äöüÄÖÜß]\w*\b")


def _const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _const(node.left), _const(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _call_name(node: ast.Call) -> str | None:
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None)


def _lt_pairs(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in {"lt", "LocalizedText"}:
            args = list(node.args) + [kw.value for kw in node.keywords if kw.arg in {"de", "en"}]
            if len(args) == 2:
                yield node, _const(args[0]), _const(args[1])


def _source_files():
    for path in sorted(SRC.rglob("*.py")):
        if "candyconc_copilot" in path.parts or path.name == "i18n.py":
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_every_bilingual_pair_is_complete():
    problems: list[str] = []
    for path, tree in _source_files():
        for node, de, en in _lt_pairs(tree):
            where = f"{path.relative_to(SRC)}:{node.lineno}"
            if de is None or en is None:
                # Computed texts (e.g. MathML built by a helper) cannot be
                # checked here.
                continue
            if not de.strip() or not en.strip():
                problems.append(f"{where}: empty text")
            is_latex = "\\" in de or "\\" in en
            if not is_latex and placeholders(de) != placeholders(en):
                problems.append(f"{where}: placeholders differ {placeholders(de)} != {placeholders(en)}")
            german_words = [w for w in _GERMAN_WORD.findall(en) if len(w) >= 3]
            if german_words:
                problems.append(f"{where}: English text contains German words {german_words}: {en[:60]!r}")
    assert problems == []


def test_every_api_error_has_a_stable_code_and_matching_params():
    problems: list[str] = []
    texts_by_code: dict[str, set[tuple[str, str]]] = {}
    for path, tree in _source_files():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node) == "ApiError"):
                continue
            where = f"{path.relative_to(SRC)}:{node.lineno}"
            if len(node.args) < 3:
                problems.append(f"{where}: ApiError(status, code, message, **params)")
                continue
            code = _const(node.args[1])
            if code is None or not _CODE.match(code):
                problems.append(f"{where}: code must be a dotted literal, got {ast.unparse(node.args[1])}")
                continue
            message = node.args[2]
            if isinstance(message, ast.Call) and _call_name(message) in {"lt", "LocalizedText"}:
                pair = next(iter(_lt_pairs(ast.Module(body=[ast.Expr(message)], type_ignores=[]))), None)
                if pair and pair[1] is not None and pair[2] is not None:
                    params = {kw.arg for kw in node.keywords if kw.arg and kw.arg != "headers"}
                    has_kwargs = any(kw.arg is None for kw in node.keywords)
                    if not has_kwargs and placeholders(pair[1]) != params:
                        problems.append(f"{where}: params {sorted(params)} != placeholders {sorted(placeholders(pair[1]))}")
                    texts_by_code.setdefault(code, set()).add((pair[1], pair[2]))
    for code, texts in texts_by_code.items():
        if len(texts) > 1:
            problems.append(f"code {code} has {len(texts)} different messages")
    assert problems == []


def test_every_api_error_code_has_one_status():
    """A code means one thing, so it answers with one HTTP status everywhere.

    ``docset.corpus_mismatch`` answered 400 in server.py and semantic.py and
    422 in the analysis routes, four more codes were split the same way.
    """
    statuses_by_code: dict[str, set[tuple[int, str]]] = {}
    for path, tree in _source_files():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node) == "ApiError"):
                continue
            if len(node.args) < 2:
                continue
            status, code = node.args[0], _const(node.args[1])
            if code is None or not (isinstance(status, ast.Constant) and isinstance(status.value, int)):
                continue
            statuses_by_code.setdefault(code, set()).add((status.value, f"{path.relative_to(SRC)}:{node.lineno}"))
    split = {
        code: sorted(sites)
        for code, sites in statuses_by_code.items()
        if len({status for status, _ in sites}) > 1
    }
    assert split == {}
