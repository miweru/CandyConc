#!/usr/bin/env python3
"""Multi-format import adapters for the Fast Index (Phase 1).

Each adapter is a thin DocRecord-path frontend: it turns an external format
(CSV / JSONL / plaintext directory / HuggingFace dataset) into an iterator of
plain ``dict`` rows and feeds it to
:func:`candyconc.ingest.build_fast_index_from_parquet.build_fast_index_from_rows`,
the shared seam (QW2). The backend, the generic doc-stream, the spaCy load and
every binary writer are reused unchanged — no backend change is required, so the
aligned parquet path stays byte-identical.

The row iterators (``iter_csv_rows`` / ``iter_jsonl_rows`` / ``iter_plaintext_rows``
/ ``iter_hf_rows``) are pure parsing functions with NO spaCy dependency, so they
are unit-testable on their own. Only the ``build_index_from_*`` wrappers load
spaCy (lazily, via the shared seam).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional

from candyconc.ingest.build_fast_index_from_parquet import (  # noqa: E402
    build_fast_index_from_rows,
    build_fast_index_prealigned,
    build_fast_index_from_prealigned_rows,
    BuildContext,
    RejectSink,
    SpacyModelMissingError,
)
from candyconc.utils.disk_preflight import check_disk_space  # noqa: E402
from candyconc.i18n import localize  # noqa: E402

LOGGER = logging.getLogger(__name__)

# Single default across CLI, REST job path and the adapter subcommands
# (previously de_core_news_sm here — a confound source: the preflight advertised
# md while the adapter defaulted to sm).
DEFAULT_SPACY_MODEL = "de_core_news_md"


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _read_text_with_fallback(path: Path) -> str:
    """Read a text file as UTF-8, falling back to charset detection then to
    UTF-8 with replacement so a single bad byte never aborts an import."""
    raw = path.read_bytes()
    # Strip a UTF-8 BOM if present.
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            import charset_normalizer  # optional dependency

            guess = charset_normalizer.from_bytes(raw).best()
            if guess is not None:
                return str(guess)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")


def _resolve_dot_path(obj: Any, dotted: str) -> Any:
    """Resolve ``a.b.c`` against nested dicts; return None if any hop is missing."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _flatten_for_columns(record: dict, columns: Iterable[str]) -> dict:
    """Return a flat dict where each requested (possibly dotted) column name is a
    top-level key, so the generic doc-stream's ``row.get(col)`` resolves it. Plain
    (non-dotted) keys are copied through; dotted keys are resolved and stored under
    their full dotted name."""
    out: dict = {}
    # Keep all top-level scalar keys so non-listed metadata is still available.
    for k, v in record.items():
        if not isinstance(v, (dict, list)):
            out[k] = v
    for col in columns:
        if col is None:
            continue
        if "." in col:
            resolved = _resolve_dot_path(record, col)
            # Don't clobber a genuine literal flat key named e.g. "a.b" with a
            # None from a failed nested lookup; prefer whichever is present.
            if resolved is not None:
                out[col] = resolved
            elif col in record:
                out[col] = record[col]
        elif col in record:
            out[col] = record[col]
    return out


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
CSV_DELIMITERS = ",;\t|"


def detect_csv_delimiter(text: str, *, suffix: str = "") -> str:
    """Delimiter of a CSV text: comma, semicolon, tab or pipe.

    Sniffs the first 8 KiB, restricted to these four. An unrestricted sniffer
    picks the space in prose, for example when a long first row carries
    quoted speech. When sniffing fails: tab for ``.tsv``, else comma. The
    import preflight uses the same function, so both read the same columns.
    """
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return "\t" if str(suffix).lower() == ".tsv" else ","


def iter_csv_rows(
    path: Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
) -> Iterator[dict]:
    """Yield each CSV row as a dict. Delimiter is auto-sniffed when not given.

    A UTF-8 BOM on the header is stripped. Rows are yielded verbatim; column
    selection happens downstream in the generic doc-stream.
    """
    path = Path(path)
    data = path.read_bytes()
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    text = data.decode(encoding, errors="replace")
    if delimiter is None:
        delimiter = detect_csv_delimiter(text, suffix=path.suffix)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    for row in reader:
        # csv.DictReader yields OrderedDict with possible None keys for ragged rows.
        yield {k: v for k, v in row.items() if k is not None}


# --------------------------------------------------------------------------- #
# JSONL
# --------------------------------------------------------------------------- #
def iter_jsonl_rows(
    path: Path,
    *,
    columns: Optional[List[str]] = None,
    reject_sink: "RejectSink | None" = None,
    max_line_bytes: int = 64 * 1024 * 1024,
) -> Iterator[dict]:
    """Yield each JSONL line as a dict, flattening any dotted ``columns`` (e.g.
    ``meta.author``) into top-level keys. Malformed / non-object / oversized lines
    are skipped (recorded in ``reject_sink`` when supplied, else logged) rather
    than aborting the import. ``max_line_bytes`` caps a single line to avoid
    buffering a pathological multi-GB line into memory.
    """
    path = Path(path)
    columns = columns or []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if len(line) > max_line_bytes:
                if reject_sink is not None:
                    reject_sink.seen()
                    reject_sink.record(i, "line_too_large", {"line": i, "bytes": len(line)})
                else:
                    LOGGER.warning("JSONL line %d exceeds %d bytes, skipped.", i, max_line_bytes)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                if reject_sink is not None:
                    reject_sink.seen()
                    reject_sink.record(i, "malformed_json", {"line": i, "error": str(exc)})
                else:
                    LOGGER.warning("JSONL line %d is invalid, skipped: %s", i, exc)
                continue
            if not isinstance(record, dict):
                if reject_sink is not None:
                    reject_sink.seen()
                    reject_sink.record(i, "non_object_line", {"line": i})
                else:
                    LOGGER.warning("JSONL line %d is not an object, skipped.", i)
                continue
            yield _flatten_for_columns(record, columns)


# --------------------------------------------------------------------------- #
# Plaintext / directory
# --------------------------------------------------------------------------- #
def _iter_plaintext_files(root: Path, pattern: str) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    root_resolved = root.resolve()
    for p in sorted(root.rglob(pattern)):
        if not p.is_file():
            continue
        # Skip symlinks (and any path) whose real target escapes the input root,
        # so a planted symlink cannot pull out-of-root content into the corpus
        # under an in-root provenance id.
        try:
            if not p.resolve().is_relative_to(root_resolved):
                LOGGER.warning("Skipping a file outside the root folder: %s", p)
                continue
        except (OSError, RuntimeError):
            LOGGER.warning("Skipping a file that cannot be resolved: %s", p)
            continue
        yield p


def iter_plaintext_rows(
    path: Path,
    *,
    pattern: str = "*.txt",
    split_paragraphs: bool = False,
    source: str = "plaintext",
) -> Iterator[dict]:
    """Yield one row per text file (or per blank-line paragraph when
    ``split_paragraphs``). Provenance is derived from the path: ``id`` is the
    path relative to ``root``; ``register`` is the immediate parent directory.

    ``source`` is set explicitly so the metadata reader does not reverse-parse a
    ``::``-bearing path (R3.8).
    """
    root = Path(path)
    for fp in _iter_plaintext_files(root, pattern):
        rel = fp.relative_to(root) if root.is_dir() else Path(fp.name)
        register = rel.parent.name or source
        content = _read_text_with_fallback(fp)
        if split_paragraphs:
            paras = [p.strip() for p in content.split("\n\n") if p.strip()]
            for j, para in enumerate(paras):
                yield {
                    "id": f"{rel.as_posix()}#{j}",
                    "text": para,
                    "register": register,
                    "source": source,
                }
        else:
            yield {
                "id": rel.as_posix(),
                "text": content,
                "register": register,
                "source": source,
            }


# --------------------------------------------------------------------------- #
# HuggingFace datasets
# --------------------------------------------------------------------------- #
def iter_hf_rows(
    dataset: str,
    *,
    config: str | None = None,
    split: str = "train",
    columns: Optional[List[str]] = None,
    streaming: bool = True,
    trust_remote_code: bool = False,
    token: str | None = None,
    limit: int | None = None,
) -> Iterator[dict]:
    """Yield rows from a HuggingFace dataset. ``datasets`` is imported lazily so
    this module stays importable without it. ``trust_remote_code`` defaults to
    False (untrusted-by-default); pass it explicitly to opt in.
    """
    from datasets import load_dataset  # lazy: optional heavy dependency

    columns = columns or []
    ds = load_dataset(
        dataset, name=config, split=split, streaming=streaming,
        trust_remote_code=trust_remote_code, token=token,
    )
    for i, record in enumerate(ds):
        if limit is not None and i >= limit:
            break
        if isinstance(record, dict):
            yield _flatten_for_columns(record, columns)


# --------------------------------------------------------------------------- #
# Build wrappers (each reuses the shared seam build_fast_index_from_rows)
# --------------------------------------------------------------------------- #
def _make_ctx(reject_policy: str | None, reject_report: Path | None) -> BuildContext:
    ctx = BuildContext()
    if reject_policy or reject_report:
        ctx.reject_sink = RejectSink(
            error_policy=(reject_policy or "collect"),  # type: ignore[arg-type]
            log_path=reject_report,
        )
    return ctx


def build_index_from_csv(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    delimiter: str | None = None,
    source: str = "csv",
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    rows = iter_csv_rows(input_path, delimiter=delimiter)
    build_fast_index_from_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column, meta_columns=meta_columns,
        source=source,
        build_info={"import_mode": "csv", "source_path": str(input_path)},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_jsonl(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    source: str = "jsonl",
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    cols = [text_column] + ([id_column] if id_column else []) + (meta_columns or [])
    rows = iter_jsonl_rows(input_path, columns=cols, reject_sink=ctx.reject_sink)
    build_fast_index_from_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column, meta_columns=meta_columns,
        source=source,
        build_info={"import_mode": "jsonl", "source_path": str(input_path)},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_prealigned_csv(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = "id",
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    delimiter: str | None = None,
    source: str = "prealigned-csv",
    variant_column: str | None = None,
    model_column: str | None = None,
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    rows = iter_csv_rows(input_path, delimiter=delimiter)
    build_fast_index_from_prealigned_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column,
        pair_key_column=pair_key_column, pair_role_column=pair_role_column,
        anchor_role=anchor_role, pair_axis=pair_axis, pair_order=pair_order,
        meta_columns=meta_columns, source=source,
        variant_column=variant_column, model_column=model_column,
        build_info={"import_mode": "prealigned", "source_path": str(input_path),
                    "source_format": "csv", "pair_axes": [pair_axis],
                    "pair_order": pair_order},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_prealigned_jsonl(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = "id",
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    source: str = "prealigned-jsonl",
    variant_column: str | None = None,
    model_column: str | None = None,
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    cols = (
        [text_column, pair_key_column, pair_role_column]
        + ([id_column] if id_column else [])
        + ([variant_column] if variant_column else [])
        + ([model_column] if model_column else [])
        + (meta_columns or [])
    )
    rows = iter_jsonl_rows(input_path, columns=cols, reject_sink=ctx.reject_sink)
    build_fast_index_from_prealigned_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column,
        pair_key_column=pair_key_column, pair_role_column=pair_role_column,
        anchor_role=anchor_role, pair_axis=pair_axis, pair_order=pair_order,
        meta_columns=meta_columns, source=source,
        variant_column=variant_column, model_column=model_column,
        build_info={"import_mode": "prealigned", "source_path": str(input_path),
                    "source_format": "jsonl", "pair_axes": [pair_axis],
                    "pair_order": pair_order},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_prealigned_parquet(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = "id",
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    source: str = "prealigned-parquet",
    variant_column: str | None = None,
    model_column: str | None = None,
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    build_fast_index_prealigned(
        input_path, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column,
        pair_key_column=pair_key_column, pair_role_column=pair_role_column,
        anchor_role=anchor_role, pair_axis=pair_axis, pair_order=pair_order,
        meta_columns=meta_columns, source=source,
        variant_column=variant_column, model_column=model_column,
        build_info={"import_mode": "prealigned", "source_path": str(input_path),
                    "source_format": "parquet", "pair_axes": [pair_axis],
                    "pair_order": pair_order},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_plaintext(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    pattern: str = "*.txt",
    split_paragraphs: bool = False,
    source: str = "plaintext",
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    rows = iter_plaintext_rows(
        input_path, pattern=pattern, split_paragraphs=split_paragraphs, source=source,
    )
    build_fast_index_from_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column="text", id_column="id", meta_columns=["register"],
        source=source,
        build_info={"import_mode": "plaintext", "source_path": str(input_path)},
        ctx=ctx, **build_kwargs,
    )


def build_index_from_hf(
    dataset: str,
    output_path: Path,
    *,
    spacy_model: str = DEFAULT_SPACY_MODEL,
    text_column: str = "text",
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    config: str | None = None,
    split: str = "train",
    streaming: bool = True,
    trust_remote_code: bool = False,
    token: str | None = None,
    limit: int | None = None,
    source: str = "huggingface",
    reject_policy: str | None = None,
    reject_report: Path | None = None,
    **build_kwargs: Any,
) -> None:
    ctx = _make_ctx(reject_policy, reject_report)
    cols = [text_column] + ([id_column] if id_column else []) + (meta_columns or [])
    rows = iter_hf_rows(
        dataset, config=config, split=split, columns=cols, streaming=streaming,
        trust_remote_code=trust_remote_code, token=token, limit=limit,
    )
    build_fast_index_from_rows(
        rows, output_path, spacy_model=spacy_model,
        text_column=text_column, id_column=id_column, meta_columns=meta_columns,
        source=source,
        build_info={
            "import_mode": "huggingface", "source_dataset": dataset,
            "hf_config": config, "hf_split": split,
        },
        ctx=ctx, **build_kwargs,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _plaintext_input_size(root: Path, pattern: str, *, max_files: int = 100_000) -> int:
    """Bounded total byte size of the plaintext input (file, or matching files)."""
    root = Path(root)
    if root.is_file():
        try:
            return int(root.stat().st_size)
        except OSError:
            return 0
    total = 0
    for i, fp in enumerate(_iter_plaintext_files(root, pattern)):
        if i >= max_files:
            break
        try:
            total += int(fp.stat().st_size)
        except OSError:
            continue
    return total


def _disk_preflight(input_size: int, output_path: Path) -> None:
    """Fail with a clear message BEFORE the build when the disk is full.

    Uses the shared factor heuristic (env-tunable, same knobs as the parquet
    builder); ``CANDYCONC_BUILD_ALLOW_LOW_DISK=1`` downgrades to a warning.
    The command line prints the English text of the bilingual message.
    """
    result = check_disk_space(input_size, output_path)
    message = localize(result.get("message"), "en")
    if result.get("blocking"):
        raise SystemExit(f"The disk space check blocks the import: {message}")
    if result.get("status") in {"warn", "unknown"}:
        LOGGER.warning("Disk space check: %s", message)


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--spacy-model", default=DEFAULT_SPACY_MODEL)
    p.add_argument("--batch-size", type=int, default=0)
    p.add_argument("--n-process", type=int, default=0)
    p.add_argument("--enable-ner", action="store_true", default=False)
    p.add_argument("--enable-deps", action="store_true", default=False)
    p.add_argument("--split-long-texts", dest="split_long_texts", action="store_true", default=True)
    p.add_argument("--no-split-long-texts", dest="split_long_texts", action="store_false")
    p.add_argument("--max-doc-chars", type=int, default=1_000_000)
    p.add_argument("--meta-index-fields", default="")
    p.add_argument("--reject-policy", choices=["collect", "fail_fast"], default="collect")
    p.add_argument("--reject-report", type=Path, default=None)
    p.add_argument(
        "--capture-whitespace", dest="capture_whitespace", action="store_true", default=True,
        help="write whitespace_after.bin, the original spacing between tokens (default: on)",
    )
    p.add_argument(
        "--no-capture-whitespace", dest="capture_whitespace", action="store_false",
        help="do not write whitespace_after.bin",
    )


def _add_prealigned(p: argparse.ArgumentParser) -> None:
    p.add_argument("--text-column", default="text")
    p.add_argument("--id-column", default="id")
    p.add_argument("--pair-key-column", default="pair_id")
    p.add_argument("--pair-role-column", default="pair_role")
    p.add_argument("--anchor-role", default="source")
    p.add_argument("--pair-axis", default="prealigned")
    p.add_argument("--pair-order", choices=("unsorted", "grouped", "sorted"), default="unsorted")
    p.add_argument("--source", default=None)
    p.add_argument("--meta-columns", nargs="*", default=None)
    p.add_argument("--variant-column", default=None)
    p.add_argument("--model-column", default=None)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Multi-format Fast Index import adapters")
    sub = parser.add_subparsers(dest="format", required=True)

    pc = sub.add_parser("csv", help="Import a CSV file")
    pc.add_argument("--input", type=Path, required=True)
    pc.add_argument("--text-column", default="text")
    pc.add_argument("--id-column", default=None)
    pc.add_argument("--meta-columns", nargs="*", default=None)
    pc.add_argument("--delimiter", default=None)
    pc.add_argument("--source", default=None)
    _add_common(pc)

    pj = sub.add_parser("jsonl", help="Import a JSONL file (dot-path fields ok)")
    pj.add_argument("--input", type=Path, required=True)
    pj.add_argument("--text-column", default="text")
    pj.add_argument("--id-column", default=None)
    pj.add_argument("--meta-columns", nargs="*", default=None)
    pj.add_argument("--source", default=None)
    _add_common(pj)

    ppp = sub.add_parser("prealigned-parquet", help="Import a pre-aligned Parquet corpus")
    ppp.add_argument("--input", type=Path, required=True)
    _add_prealigned(ppp)
    _add_common(ppp)

    ppc = sub.add_parser("prealigned-csv", help="Import a pre-aligned CSV corpus")
    ppc.add_argument("--input", type=Path, required=True)
    ppc.add_argument("--delimiter", default=None)
    _add_prealigned(ppc)
    _add_common(ppc)

    ppj = sub.add_parser("prealigned-jsonl", help="Import a pre-aligned JSONL corpus")
    ppj.add_argument("--input", type=Path, required=True)
    _add_prealigned(ppj)
    _add_common(ppj)

    pp = sub.add_parser("plaintext", help="Import a plaintext file/dir/glob")
    pp.add_argument("--input", type=Path, required=True)
    pp.add_argument("--pattern", default="*.txt")
    pp.add_argument("--split-paragraphs", action="store_true", default=False)
    pp.add_argument("--source", default=None)
    _add_common(pp)

    ph = sub.add_parser("hf", help="Import a HuggingFace dataset")
    # ``--input`` is an alias for ``--dataset`` so generic dispatchers
    # (candy import / the REST import-job runner) can pass the dataset id
    # through their uniform ``--input`` slot.
    ph.add_argument("--dataset", "--input", dest="dataset", required=True)
    ph.add_argument("--text-column", default="text")
    ph.add_argument("--id-column", default=None)
    ph.add_argument("--meta-columns", nargs="*", default=None)
    ph.add_argument("--config", default=None)
    ph.add_argument("--split", default="train")
    ph.add_argument("--no-streaming", action="store_true", default=False)
    ph.add_argument("--trust-remote-code", action="store_true", default=False)
    ph.add_argument("--source", default=None)
    ph.add_argument("--limit", type=int, default=None)
    _add_common(ph)

    args = parser.parse_args(argv)
    meta_index_fields = [f.strip() for f in args.meta_index_fields.split(",") if f.strip()]
    common = dict(
        spacy_model=args.spacy_model, batch_size=args.batch_size,
        n_process=args.n_process, reject_policy=args.reject_policy,
        reject_report=args.reject_report,
        disable_ner=not args.enable_ner,
        disable_deps=not args.enable_deps,
        split_long_texts=args.split_long_texts,
        max_doc_chars=args.max_doc_chars,
        meta_index_fields=meta_index_fields or None,
        capture_whitespace=args.capture_whitespace,
    )

    # Disk-Space-Preflight: klarer Fehler VOR dem Build bei voller Platte
    # (Faktor-Heuristik geteilt mit dem Parquet-Builder, env-tunebar).
    if args.format == "plaintext":
        _disk_preflight(_plaintext_input_size(args.input, args.pattern), args.output)
    elif args.format != "hf":
        try:
            input_size = int(Path(args.input).stat().st_size)
        except OSError:
            input_size = 0
        _disk_preflight(input_size, args.output)

    try:
        return _dispatch(args, common)
    except SpacyModelMissingError as exc:
        # Nutzerfertige Meldung ohne Traceback — selber Fehlerpfad wie der
        # Parquet-Builder (der failed-build_report wurde bereits geschrieben).
        LOGGER.error("%s", exc)
        raise SystemExit(2) from exc


def _dispatch(args: argparse.Namespace, common: dict) -> int:
    if args.format == "csv":
        build_index_from_csv(
            args.input, args.output, text_column=args.text_column,
            id_column=args.id_column, meta_columns=args.meta_columns,
            delimiter=args.delimiter,
            **({"source": args.source} if args.source else {}),
            **common,
        )
    elif args.format == "jsonl":
        build_index_from_jsonl(
            args.input, args.output, text_column=args.text_column,
            id_column=args.id_column, meta_columns=args.meta_columns,
            **({"source": args.source} if args.source else {}),
            **common,
        )
    elif args.format == "prealigned-parquet":
        build_index_from_prealigned_parquet(
            args.input, args.output, text_column=args.text_column,
            id_column=args.id_column, pair_key_column=args.pair_key_column,
            pair_role_column=args.pair_role_column, anchor_role=args.anchor_role,
            pair_axis=args.pair_axis, pair_order=args.pair_order,
            meta_columns=args.meta_columns,
            source=args.source or "prealigned-parquet",
            variant_column=args.variant_column, model_column=args.model_column,
            **common,
        )
    elif args.format == "prealigned-csv":
        build_index_from_prealigned_csv(
            args.input, args.output, text_column=args.text_column,
            id_column=args.id_column, pair_key_column=args.pair_key_column,
            pair_role_column=args.pair_role_column, anchor_role=args.anchor_role,
            pair_axis=args.pair_axis, pair_order=args.pair_order,
            meta_columns=args.meta_columns,
            delimiter=args.delimiter, source=args.source or "prealigned-csv",
            variant_column=args.variant_column,
            model_column=args.model_column, **common,
        )
    elif args.format == "prealigned-jsonl":
        build_index_from_prealigned_jsonl(
            args.input, args.output, text_column=args.text_column,
            id_column=args.id_column, pair_key_column=args.pair_key_column,
            pair_role_column=args.pair_role_column, anchor_role=args.anchor_role,
            pair_axis=args.pair_axis, pair_order=args.pair_order,
            meta_columns=args.meta_columns,
            source=args.source or "prealigned-jsonl",
            variant_column=args.variant_column, model_column=args.model_column,
            **common,
        )
    elif args.format == "plaintext":
        build_index_from_plaintext(
            args.input, args.output, pattern=args.pattern,
            split_paragraphs=args.split_paragraphs,
            **({"source": args.source} if args.source else {}),
            **common,
        )
    elif args.format == "hf":
        build_index_from_hf(
            args.dataset, args.output, text_column=args.text_column,
            id_column=args.id_column, meta_columns=args.meta_columns,
            config=args.config, split=args.split, streaming=not args.no_streaming,
            trust_remote_code=args.trust_remote_code, limit=args.limit,
            **({"source": args.source} if args.source else {}),
            **common,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
