"""Every import records the original spacing (``whitespace_after.bin``).

Before builder revision 3 only the Parquet builder wrote the side file, and
only with ``--capture-whitespace``. ``candy import`` (CSV, JSONL, plain text,
Parquet, VRT, Hugging Face), the adapter subcommands and the import jobs of
the web interface never wrote it, so concordance lines read
"soul . No words" and "TRUMAN 'S ADDRESS" instead of the text as written.

Now every import writes it unless ``--no-capture-whitespace`` (or the job
option ``capture_whitespace: false``) switches it off, and the manifest field
``whitespace`` names where the spacing comes from. A VRT file imported with
``--annotation-mode adopt`` has tokens without spacing: no side file, and the
manifest and the VRT report say so.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("spacy", reason="spaCy not installed")

TEXT_A = "He was a heroic champion of justice and freedom. Tragic fate, it seems!"
TEXT_B = "TRUMAN'S ADDRESS: no words can soothe the soul. No words."


def _flags(index_dir: Path) -> np.ndarray | None:
    from candyconc.core.index_format import read_count_prefixed_array

    return read_count_prefixed_array(
        index_dir / "whitespace_after.bin", np.uint8, label="whitespace_after", missing_ok=True
    )


def _manifest(index_dir: Path) -> dict:
    return json.loads((index_dir / "index_manifest.json").read_text("utf-8"))


def _full_text(index_dir: Path, doc: int) -> str:
    """The document text as the reader shows it (flags when present)."""
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core.source_spacing import join_tokens, whitespace_flags

    idx = CorpusIndex(index_dir, read_only=True)
    try:
        bounds = idx.fast_index.boundaries.document._positions
        start = int(bounds[doc])
        end = int(bounds[doc + 1]) if doc + 1 < bounds.size else int(idx.fast_index.token_store.token_count)
        lex = idx.fast_index.lexicons.word
        ids = idx.fast_index.token_store.word_stream.get_range(start, end)
        tokens = [str(lex.get_string(int(i))) for i in ids]
        ws = whitespace_flags(idx)
        return " ".join(tokens) if ws is None else join_tokens(tokens, start, ws)
    finally:
        idx.close()


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    csv = tmp_path / "in.csv"
    csv.write_text(
        "id,text\n" + "\n".join(f'd{i},"{t}"' for i, t in enumerate([TEXT_A, TEXT_B])) + "\n",
        encoding="utf-8",
    )
    jsonl = tmp_path / "in.jsonl"
    jsonl.write_text(
        "\n".join(json.dumps({"id": f"d{i}", "text": t}) for i, t in enumerate([TEXT_A, TEXT_B])) + "\n",
        encoding="utf-8",
    )
    txt_dir = tmp_path / "txt"
    txt_dir.mkdir()
    (txt_dir / "a.txt").write_text(TEXT_A, encoding="utf-8")
    (txt_dir / "b.txt").write_text(TEXT_B, encoding="utf-8")
    paired = tmp_path / "paired.csv"
    paired.write_text(
        "id,pair_id,pair_role,text\n"
        f'a,p1,source,"{TEXT_A}"\n'
        f'b,p1,version,"{TEXT_B}"\n',
        encoding="utf-8",
    )
    out = {"csv": csv, "jsonl": jsonl, "plaintext": txt_dir, "prealigned-csv": paired}
    pl = pytest.importorskip("polars")
    parquet = tmp_path / "in.parquet"
    pl.DataFrame({"id": ["d0", "d1"], "text": [TEXT_A, TEXT_B]}).write_parquet(parquet)
    out["parquet"] = parquet
    return out


def _candy_import(monkeypatch, argv: list[str]) -> None:
    from candyconc.entrypoints import cli as candy_cli

    monkeypatch.setattr(sys, "argv", ["candy", "import", *argv])
    candy_cli.main()


FORMATS = ["csv", "jsonl", "plaintext", "parquet", "prealigned-csv"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_candy_import_writes_the_spacing_by_default(tmp_path, monkeypatch, fmt):
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    inputs = _write_inputs(tmp_path)
    out = tmp_path / f"idx_{fmt}"
    argv = ["--input", str(inputs[fmt]), "--output", str(out), "--spacy-model", "blank:en",
            "--batch-size", "4", "--n-process", "1", "--input-format", fmt]
    _candy_import(monkeypatch, argv)

    flags = _flags(out)
    assert flags is not None, "whitespace_after.bin is missing"
    manifest = _manifest(out)
    assert manifest["capabilities"]["whitespace_after"] is True
    assert manifest["whitespace"] == "text"
    assert json.loads((out / "index_build_meta.json").read_text("utf-8"))["capture_whitespace"] is True
    texts = {_full_text(out, 0), _full_text(out, 1)}
    assert texts == {TEXT_A, TEXT_B}


@pytest.mark.parametrize("fmt", FORMATS)
def test_no_capture_whitespace_switches_it_off(tmp_path, monkeypatch, fmt):
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    inputs = _write_inputs(tmp_path)
    out = tmp_path / f"idx_{fmt}_off"
    argv = ["--input", str(inputs[fmt]), "--output", str(out), "--spacy-model", "blank:en",
            "--batch-size", "4", "--n-process", "1", "--input-format", fmt,
            "--no-capture-whitespace"]
    _candy_import(monkeypatch, argv)

    assert _flags(out) is None
    manifest = _manifest(out)
    assert manifest["capabilities"]["whitespace_after"] is False
    assert manifest["whitespace"] == "disabled"
    # The old display: every token separated by one space.
    assert "freedom . Tragic fate ," in (_full_text(out, 0) + _full_text(out, 1))


def test_counts_and_positions_do_not_depend_on_the_side_file(tmp_path, monkeypatch):
    """Tokens, documents, sentences and hits are identical with and without it."""
    from candyconc.core.corpus_index import CorpusIndex

    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    inputs = _write_inputs(tmp_path)
    on, off = tmp_path / "on", tmp_path / "off"
    base = ["--input", str(inputs["csv"]), "--spacy-model", "blank:en", "--batch-size", "4", "--n-process", "1"]
    _candy_import(monkeypatch, [*base, "--output", str(on)])
    _candy_import(monkeypatch, [*base, "--output", str(off), "--no-capture-whitespace"])

    ignore = {"whitespace_after.bin", "index_manifest.json", "index_build_meta.json",
              "build_report.json", "build_report.md", "build.log", "reject_report.json"}
    files_on = {p.name for p in on.iterdir()} - ignore
    files_off = {p.name for p in off.iterdir()} - ignore
    assert files_on == files_off
    for name in sorted(files_on):
        if (on / name).is_file():
            assert (on / name).read_bytes() == (off / name).read_bytes(), name
    a, b = CorpusIndex(on, read_only=True), CorpusIndex(off, read_only=True)
    try:
        assert a.token_count() == b.token_count()
        assert _manifest(on)["build_fingerprint"] == _manifest(off)["build_fingerprint"]
    finally:
        a.close()
        b.close()


def test_adapter_subcommands_write_the_spacing(tmp_path, monkeypatch):
    from candyconc.ingest import ingest_adapters

    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    inputs = _write_inputs(tmp_path)
    out = tmp_path / "adapter_csv"
    assert ingest_adapters.main(
        ["csv", "--input", str(inputs["csv"]), "--output", str(out), "--spacy-model", "blank:en",
         "--batch-size", "4", "--n-process", "1"]
    ) == 0
    assert _flags(out) is not None
    off = tmp_path / "adapter_csv_off"
    assert ingest_adapters.main(
        ["csv", "--input", str(inputs["csv"]), "--output", str(off), "--spacy-model", "blank:en",
         "--batch-size", "4", "--n-process", "1", "--no-capture-whitespace"]
    ) == 0
    assert _flags(off) is None


def test_hugging_face_import_forwards_the_switch(monkeypatch, tmp_path):
    """HF has no offline dataset here: the argv of the builder is checked."""
    from types import ModuleType

    from candyconc.builders import _runner
    from candyconc.ingest import pipelines

    recorder: dict = {}
    stub = ModuleType("candyconc.builders._stub_ws_builder")

    def _main(argv):
        recorder.setdefault("argvs", []).append(list(argv))
        return 0

    stub.main = _main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "candyconc.builders._stub_ws_builder", stub)
    monkeypatch.setitem(_runner._INPROCESS_MODULES, "ingest_adapters.py", ("candyconc.builders._stub_ws_builder",))
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: True)
    base = ["--input", "user/dataset", "--input-format", "hf", "--spacy-model", "blank:en"]
    _candy_import(monkeypatch, [*base, "--output", str(tmp_path / "a")])
    _candy_import(monkeypatch, [*base, "--output", str(tmp_path / "b"), "--no-capture-whitespace"])
    first, second = recorder["argvs"]
    assert "--no-capture-whitespace" not in first
    assert "--no-capture-whitespace" in second
    # The adapter parses the flag for hf like for every other subcommand.
    from candyconc.ingest import ingest_adapters

    seen: dict = {}
    monkeypatch.setattr(ingest_adapters, "build_index_from_hf", lambda *a, **kw: seen.update(kw))
    assert ingest_adapters.main(["hf", "--dataset", "user/dataset", "--output", str(tmp_path / "c"),
                                 "--no-capture-whitespace"]) == 0
    assert seen["capture_whitespace"] is False
    assert ingest_adapters.main(["hf", "--dataset", "user/dataset", "--output", str(tmp_path / "d")]) == 0
    assert seen["capture_whitespace"] is True


VRT = "\n".join(
    [
        '<text id="t1" source="demo">',
        "<s>",
        "Tea\ttea\tNOUN",
        "is\tbe\tAUX",
        "good\tgood\tADJ",
        ".\t.\tPUNCT",
        "</s>",
        "</text>",
    ]
)


def _build_vrt(tmp_path, monkeypatch, *extra) -> Path:
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    module = importlib.import_module("candyconc.ingest.build_fast_index_from_vrt")
    vrt = tmp_path / "demo.vrt"
    vrt.write_text(VRT, encoding="utf-8")
    out = tmp_path / ("idx" + "_".join(extra).replace("-", ""))
    monkeypatch.setattr(
        sys, "argv",
        ["build_fast_index_from_vrt.py", "--input", str(vrt), "--output", str(out),
         "--token-columns", "word,lemma,pos", *extra],
    )
    assert module.main() == 0
    return out


def test_vrt_with_spacy_records_the_spacing_of_the_rebuilt_text(tmp_path, monkeypatch):
    out = _build_vrt(tmp_path, monkeypatch, "--spacy-model", "blank:en", "--batch-size", "4", "--n-process", "1")
    assert _flags(out).tolist() == [1, 1, 0, 0]
    assert _manifest(out)["whitespace"] == "vrt_join"
    assert json.loads((out / "vrt_import_report.json").read_text("utf-8"))["whitespace"] == "vrt_join"
    assert _full_text(out, 0) == "Tea is good."


def test_vrt_adopt_has_no_spacing_and_says_so(tmp_path, monkeypatch):
    out = _build_vrt(tmp_path, monkeypatch, "--annotation-mode", "adopt")
    assert _flags(out) is None
    manifest = _manifest(out)
    assert manifest["whitespace"] == "pretokenized"
    assert manifest["capabilities"]["whitespace_after"] is False
    report = json.loads((out / "vrt_import_report.json").read_text("utf-8"))
    assert report["whitespace"] == "pretokenized"
    assert "without their original spacing" in report["whitespace_note"]
    assert _full_text(out, 0) == "Tea is good ."


def test_import_job_option_switches_the_side_file():
    from candyconc.services.backend.corpus_import_jobs import (
        import_method_descriptors,
        iter_method_options,
    )

    descriptors = {d["method"]: d for d in import_method_descriptors()}

    for method in ("csv", "jsonl", "plaintext", "hf", "parquet", "vrt", "prealigned_csv"):
        default = iter_method_options(method, {"input": "x", "spacy_model": "blank:en"})
        assert ["--no-capture-whitespace"] not in default, method
        off = iter_method_options(method, {"input": "x", "spacy_model": "blank:en", "capture_whitespace": False})
        assert ["--no-capture-whitespace"] in off, method
        on = iter_method_options(method, {"input": "x", "spacy_model": "blank:en", "capture_whitespace": True})
        assert ["--no-capture-whitespace"] not in on, method
        spec = next(s for s in descriptors[method]["option_specs"] if s["key"] == "capture_whitespace")
        assert spec["type"] == "boolean" and spec["default"] is True
