"""Import texts follow the request language (Accept-Language).

The import manager shows the server texts directly: method labels and
descriptions, option specs, preflight check labels and messages, and error
details. Without a supported Accept-Language the German texts stay exactly as
before. With ``Accept-Language: en`` the same routes answer in English, and
error answers carry a stable ``code``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

import pytest

from candyconc.i18n import exception_text, language_scope, localize

EN = {"Accept-Language": "en, de;q=0.5"}
DE = {"Accept-Language": "de, en;q=0.5"}
_GERMAN_LETTERS = re.compile(r"[äöüÄÖÜß]")


@pytest.fixture(autouse=True)
def _pipeline_installed(monkeypatch):
    """The spaCy pipeline check has its own tests. Here it counts as installed."""
    from candyconc.ingest import pipelines

    monkeypatch.setattr(pipelines, "pipeline_installed", lambda _name: True)


def _client():
    from fastapi.testclient import TestClient
    from candyconc.services.backend.server import app

    return TestClient(app, raise_server_exceptions=False)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _methods(response) -> dict[str, dict[str, Any]]:
    assert response.status_code == 200, response.text
    return {item["method"]: item for item in response.json()["methods"]}


def _specs(method: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {spec["key"]: spec for spec in method["option_specs"]}


# --- import methods -------------------------------------------------------------


def test_import_methods_follow_the_request_language():
    client = _client()
    en = _methods(client.get("/api/v1/corpora/import-methods", headers=EN))
    de = _methods(client.get("/api/v1/corpora/import-methods"))
    explicit_de = _methods(client.get("/api/v1/corpora/import-methods", headers=DE))
    assert de == explicit_de

    assert en["csv"]["description"] == "Unpaired CSV/TSV tables with configurable text and ID columns."
    assert de["csv"]["description"] == "Ungepaarte CSV/TSV-Tabellen mit konfigurierbarer Text- und ID-Spalte."
    assert en["hf"]["label"] == "Hugging Face dataset"
    assert de["hf"]["label"] == "HuggingFace-Dataset"
    assert _specs(en["csv"])["text_column"]["label"] == "Text column"
    assert _specs(de["csv"])["text_column"]["label"] == "Textspalte"
    assert _specs(en["prealigned_csv"])["reject_policy"]["label"] == "Reject policy"
    pair_order_en = {c["value"]: c["label"] for c in _specs(en["prealigned_csv"])["pair_order"]["choices"]}
    pair_order_de = {c["value"]: c["label"] for c in _specs(de["prealigned_csv"])["pair_order"]["choices"]}
    assert pair_order_en["unsorted"] == "unsorted" and pair_order_de["unsorted"] == "unsortiert"
    en_reports = {r["key"]: r["label"] for r in en["prealigned_csv"]["reports"]}
    assert en_reports["reject_report"] == "Rejected rows report"
    assert "Kosten" in _specs(de["parquet"])["build_word_faiss"]["description"]
    assert "Cost" in _specs(en["parquet"])["build_word_faiss"]["description"]
    # Structure and machine values do not depend on the language.
    assert set(en) == set(de)
    for name in en:
        assert en[name]["option_keys"] == de[name]["option_keys"], name
        assert en[name]["emitted_features"] == de[name]["emitted_features"], name


def test_english_import_methods_contain_no_german_text():
    client = _client()
    en = _methods(client.get("/api/v1/corpora/import-methods", headers=EN))
    german = sorted({text for text in _strings(en) if _GERMAN_LETTERS.search(text)})
    assert german == []


# --- preflight ------------------------------------------------------------------


def _csv_without_text_column(tmp_path: Path) -> Path:
    source = tmp_path / "sample.csv"
    source.write_text("doc_id,body\nd1,The river rose.\n", encoding="utf-8")
    return source


def test_preflight_follows_the_request_language(tmp_path):
    client = _client()
    source = _csv_without_text_column(tmp_path)
    payload = {"method": "csv", "input_path": str(source), "text_column": "text"}
    en = client.post("/api/v1/corpora/import-preflight", json=payload, headers=EN)
    de = client.post("/api/v1/corpora/import-preflight", json=payload)
    assert en.status_code == de.status_code == 200, (en.text, de.text)
    en_body, de_body = en.json(), de.json()

    assert en_body["summary"] == "The preflight check blocks the import."
    assert de_body["summary"] == "Preflight blockiert den Import."
    en_check = next(c for c in en_body["checks"] if c["key"] == "column:text")
    de_check = next(c for c in de_body["checks"] if c["key"] == "column:text")
    assert en_check["label"] == "Text column" and de_check["label"] == "Textspalte"
    assert en_check["message"] == (
        "Required text column is missing: text. Text candidate(s) found: body. "
        "Set text_column to the matching column if it contains the document text."
    )
    assert de_check["message"].startswith("Erforderliche Textspalte fehlt: text.")
    assert en_check["message"] in en_body["errors"]
    suggestion = en_body["evidence"]["column_mapping_suggestions"][0]
    assert suggestion["safe_mapping"] == "Set text_column=body if this column contains the document text."
    # Status values are machine values and stay the same.
    assert [c["key"] for c in en_body["checks"]] == [c["key"] for c in de_body["checks"]]
    assert [c["status"] for c in en_body["checks"]] == [c["status"] for c in de_body["checks"]]


def test_preflight_function_keeps_both_languages(tmp_path):
    from candyconc.services.backend import corpus_import_jobs as jobs

    source = _csv_without_text_column(tmp_path)
    result = jobs.preflight_import_job("csv", str(source), {"text_column": "text"})
    method_check = next(c for c in result["checks"] if c["key"] == "method_supported")
    assert method_check["label"] == "Importmethode"
    assert method_check["label"].en == "Import method"
    with language_scope("en"):
        english = localize(result)
    assert english["summary"] == "The preflight check blocks the import."
    assert localize(result)["summary"] == "Preflight blockiert den Import."


def test_target_name_error_keeps_both_languages():
    from candyconc.services.backend import corpus_import_jobs as jobs

    with pytest.raises(ValueError) as caught:
        jobs._safe_target_name("../escape")
    assert str(caught.value) == "target_name ist kein sicherer Korpusname: '../escape'"
    assert exception_text(caught.value).en == "target_name is not a safe corpus name: '../escape'"


def test_disk_space_message_is_bilingual(monkeypatch, tmp_path):
    from collections import namedtuple

    from candyconc.utils import disk_preflight

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(disk_preflight.shutil, "disk_usage", lambda _p: usage(100, 90, 10))
    monkeypatch.delenv(disk_preflight.ALLOW_LOW_DISK_ENV, raising=False)
    result = disk_preflight.check_disk_space(1000, tmp_path)
    assert result["status"] == "fail"
    assert result["message"].startswith("Wenig freier Speicher für den Build")
    assert result["message"].en.startswith("Low free disk space for the build")
    # Sizes are readable units, not raw byte counts (free=14481563648).
    assert "10 B frei" in result["message"] and "10 B free" in result["message"].en
    assert "Reserve 5,0 GB" in result["message"] and "reserve of 5.0 GB" in result["message"].en


def test_disk_sizes_are_readable_units():
    from candyconc.utils.disk_preflight import size_text

    assert size_text(584) == "584 B" and size_text(584).en == "584 B"
    assert size_text(1460) == "1,4 KB" and size_text(1460).en == "1.4 KB"
    assert size_text(14481563648) == "13,5 GB" and size_text(14481563648).en == "13.5 GB"


def test_unreadable_import_outcome_warning_is_bilingual(tmp_path):
    from candyconc.services.backend.corpus_import_outcome import IMPORT_OUTCOME_FILENAME, read_import_outcome

    (tmp_path / IMPORT_OUTCOME_FILENAME).write_text("{not json", encoding="utf-8")
    outcome = read_import_outcome(tmp_path)
    warning = outcome["import_warnings"][0]
    assert warning == "Der gespeicherte Importausgang ist nicht lesbar und muss geprüft werden."
    assert warning.en == "The stored import outcome cannot be read and must be checked."


# --- errors ---------------------------------------------------------------------


def test_import_errors_carry_a_code_and_follow_the_request_language():
    client = _client()
    en = client.get("/api/v1/corpora/imports/no-such-job", headers=EN)
    de = client.get("/api/v1/corpora/imports/no-such-job")
    assert en.status_code == de.status_code == 404
    assert en.json()["detail"] == "Import job not found"
    assert de.json()["detail"] == "Importjob nicht gefunden"
    assert en.json()["code"] == de.json()["code"] == "import.job_not_found"

    missing_en = client.post("/api/v1/corpora/imports", json={"method": "csv"}, headers=EN)
    missing_de = client.post("/api/v1/corpora/imports", json={"method": "csv"})
    assert missing_en.status_code == missing_de.status_code == 400
    assert missing_en.json()["detail"] == "input_path is missing"
    assert missing_de.json()["detail"] == "input_path fehlt"
    assert missing_en.json()["code"] == "import.input_path_missing"


def test_corpus_errors_follow_the_request_language(tmp_path):
    client = _client()
    hidden_en = client.get("/api/v1/corpora/.imports/capabilities", headers=EN)
    hidden_de = client.get("/api/v1/corpora/.imports/capabilities")
    assert hidden_en.status_code == hidden_de.status_code == 404
    assert hidden_en.json()["detail"] == "Corpus not found: .imports"
    assert hidden_de.json()["detail"] == "Korpus nicht gefunden: .imports"
    assert hidden_en.json()["code"] == "corpus.not_found"
    assert hidden_en.json()["params"] == {"name": ".imports"}

    missing = tmp_path / "no-such-index"
    register_en = client.post("/api/v1/corpora/register", json={"path": str(missing)}, headers=EN)
    register_de = client.post("/api/v1/corpora/register", json={"path": str(missing)})
    assert register_en.status_code == register_de.status_code == 404
    assert register_en.json()["detail"] == f"Corpus directory not found: {missing.resolve()}"
    assert register_de.json()["detail"] == f"Korpusverzeichnis nicht gefunden: {missing.resolve()}"


def test_blocked_import_carries_the_localized_preflight(tmp_path):
    client = _client()
    source = _csv_without_text_column(tmp_path)
    payload = {"method": "csv", "input_path": str(source), "text_column": "text", "target_name": "demo"}
    en = client.post("/api/v1/corpora/imports", json=payload, headers=EN)
    de = client.post("/api/v1/corpora/imports", json=payload)
    assert en.status_code == de.status_code == 400
    assert en.json()["detail"]["message"] == "The import preflight check blocks the import."
    assert de.json()["detail"]["message"] == "Import-Preflight blockiert den Import."
    assert en.json()["detail"]["preflight"]["summary"] == "The preflight check blocks the import."


def test_import_outcome_file_keeps_both_languages(tmp_path):
    from candyconc.i18n import localize, lt
    from candyconc.services.backend.corpus_import_outcome import (
        read_import_outcome,
        write_import_outcome,
    )

    warning = lt("12 Zeilen verworfen.", "12 rows rejected.")
    write_import_outcome(tmp_path, {"import_warnings": [warning, "plain"], "partial_input": True})
    outcome = read_import_outcome(tmp_path)
    assert outcome["import_warnings"] == ["12 Zeilen verworfen.", "plain"]
    assert localize(outcome, "en")["import_warnings"] == ["12 rows rejected.", "plain"]
    # Files written before the pairs held plain strings and stay readable.
    import json

    marker = tmp_path / "import_outcome.json"
    raw = json.loads(marker.read_text("utf-8"))
    raw["import_warnings"] = ["alt"]
    marker.write_text(json.dumps(raw), "utf-8")
    assert read_import_outcome(tmp_path)["import_warnings"] == ["alt"]
