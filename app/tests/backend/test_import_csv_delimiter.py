"""The import preflight reads a CSV with the builder's delimiter detection.

A CSV whose first row is longer than the 8 KiB sample and carries quoted
speech made the unrestricted csv.Sniffer of the preflight pick the space. The
preflight then saw one column, reported the text column as missing and
blocked a file the builder imports correctly.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from candyconc.ingest.ingest_adapters import detect_csv_delimiter, iter_csv_rows
from candyconc.services.backend import corpus_import_jobs as jobs

_SENTENCES = (
    'The speaker recalled a leader who said: "I intend to ask for nothing that is not clearly right." '
    'And he promised, that "the honor of the country shall never suffer." '
    "That was the policy of the time {i}, and it served the people well in years of trouble and in years of peace. "
)


def _prose_csv(path: Path) -> Path:
    text = " ".join(_SENTENCES.format(i=i) for i in range(40))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "text", "president", "year"])
    writer.writerow(["d1", text, "Truman", "1945"])
    writer.writerow(["d2", text.replace("leader", "president"), "Truman", "1946"])
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def test_prose_csv_keeps_its_comma_delimiter(tmp_path: Path):
    src = _prose_csv(tmp_path / "speeches.csv")
    assert detect_csv_delimiter(src.read_text()) == ","
    rows = list(iter_csv_rows(src))
    assert [row["id"] for row in rows] == ["d1", "d2"]


def test_preflight_sees_the_columns_the_builder_reads(tmp_path: Path):
    src = _prose_csv(tmp_path / "speeches.csv")
    managed = tmp_path / "corpora"
    managed.mkdir()
    result = jobs.preflight_import_job(
        "csv",
        str(src),
        {"target_name": "speeches", "spacy_model": "blank:en", "__managed_corpus_dir": str(managed)},
    )
    failed = [check for check in result["checks"] if check.get("status") == "fail"]
    assert result.get("blocking") is False, failed
    assert {"id", "text", "president", "year"} <= set(result["evidence"]["columns"])


def test_tsv_without_detectable_delimiter_falls_back_to_tab():
    assert detect_csv_delimiter("single", suffix=".tsv") == "\t"
    assert detect_csv_delimiter("single", suffix=".csv") == ","
