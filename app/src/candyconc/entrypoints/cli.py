# mypy: ignore-errors

import argparse
import logging
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile

if __package__ in (None, "", "__main__"):
    # Ensure repo root is on sys.path when executed directly
    sys.path.append(str(Path(__file__).resolve().parents[2]))

import uvicorn
from candyconc.logging_config import init_logging
from candyconc.config import load_settings
from candyconc.domain.corpus import has_index
from candyconc.i18n import exception_text, localize
from candyconc.utils.import_builders import (
    find_builder_script,
    import_builder_spec,
    normalize_import_method,
)

_UNSAFE_NETWORK_DEV_OVERRIDE = "CANDYCONC_ALLOW_UNSAFE_NETWORK_DEV"


def _normalized_bind_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    return normalized


def _is_loopback_bind_host(host: str) -> bool:
    normalized = _normalized_bind_host(host)
    if normalized == "localhost":
        return True
    try:
        from ipaddress import ip_address

        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _unsafe_network_dev_override_enabled() -> bool:
    raw = os.environ.get(_UNSAFE_NETWORK_DEV_OVERRIDE, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _enforce_network_bind_security(host: str) -> None:
    if _is_loopback_bind_host(host):
        return
    from candyconc.services.backend import auth

    if not auth.is_local_dev_unsafe_mode():
        return
    if _unsafe_network_dev_override_enabled():
        logging.getLogger(__name__).critical(
            "CandyConc starts in the UNSAFE local development mode on a network "
            "address (%s). Use this only in an isolated development environment.",
            host,
        )
        return
    raise SystemExit(
        "Unsafe network start blocked: --host binds to more than the loopback "
        "address, but CANDYCONC_SECURITY_MODE=local_dev_unsafe is active. Use the "
        "release security mode, or set CANDYCONC_ALLOW_UNSAFE_NETWORK_DEV=1 on purpose."
    )


def _migrate_project(argv: list[str]) -> None:
    """Run the explicit, backup-aware migration for retired project formats."""
    parser = argparse.ArgumentParser(
        prog="candy migrate-project",
        description="Migrate a legacy .ccproj project without implicit data rewrites.",
    )
    parser.add_argument("project", help="Legacy .ccproj or JSON project file")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--output", help="Write a new migrated project file")
    target.add_argument("--in-place", action="store_true", help="Replace the source after backup")
    parser.add_argument("--backup", help="Required backup path for --in-place")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing")
    args = parser.parse_args(argv)

    if args.backup and not args.in_place:
        parser.error("--backup is only allowed together with --in-place")
    if args.in_place and not args.dry_run and not args.backup:
        parser.error("--in-place needs an explicit --backup path")

    from candyconc.project import (
        ProjectMigrationError,
        prepare_project_migration,
        project_inventory,
        write_migrated_project,
    )

    source = Path(args.project).expanduser().resolve()
    try:
        data = prepare_project_migration(source)
    except ProjectMigrationError as exc:
        raise SystemExit(localize(exception_text(exc), "en")) from exc
    inventory = project_inventory(data)
    summary = ", ".join(f"{name}={count}" for name, count in inventory.items())

    if args.dry_run or (not args.output and not args.in_place):
        print(f"Dry run passed: {source} ({summary}). No file was changed.")
        return

    try:
        if args.in_place:
            backup = Path(args.backup).expanduser().resolve()
            if backup == source:
                parser.error("--backup must not point to the source file")
            if backup.exists():
                parser.error(f"Backup already exists: {backup}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            write_migrated_project(source, data, overwrite=True)
            destination = source
        else:
            destination = Path(args.output).expanduser().resolve()
            if destination == source:
                parser.error("For the source file, use --in-place with --backup")
            write_migrated_project(destination, data)
    except ProjectMigrationError as exc:
        raise SystemExit(localize(exception_text(exc), "en")) from exc

    print(
        f"Migration completed: {source} -> {destination} ({summary}). "
        + (f"Backup: {backup}" if args.in_place else "Source unchanged.")
    )


def _parquet_layout(path: Path, text_column: str, *, aligned_options: bool) -> str:
    """``generic`` for an ordinary table, ``aligned`` for the paired research layout.

    The aligned layout has ``target_text`` (and usually ``input_text``) and no
    column of the chosen text column name. The aligned-only options
    ``--include-prompts`` and ``--allow-missing-input-text`` select it too.
    """
    if aligned_options:
        return "aligned"
    try:
        import pyarrow.parquet as pq

        names = list(pq.read_schema(path).names)
    except Exception:
        # Unreadable here: the builder reports the problem with its own checks.
        return "generic"
    if text_column in names:
        return "generic"
    if "target_text" in names:
        print(
            "The Parquet file has no column '%s' but target_text: importing it in the "
            "paired layout of the research data model." % text_column,
            file=sys.stderr,
        )
        return "aligned"
    raise SystemExit(
        f"The Parquet file has no column '{text_column}'. Its columns: {', '.join(names)}. "
        "Choose the column with the document text with --text-column."
    )


def _replacement_build_dir(output: Path) -> Path | None:
    """Where to build when ``output`` already holds an index, else ``None``.

    Writing into the folder of an existing index would change files that a
    running CandyConc has mapped into memory: its searches would mix old and
    new files, and a failed import would leave neither corpus. The new index
    is built in a hidden sibling folder (the corpus catalog skips hidden
    folders) and swapped in at the end.
    """
    if not (output.is_dir() and (output / "meta.bin").exists()):
        return None
    return output.parent / f".{output.name}.import-{os.getpid()}"


def _swap_in_index(build_dir: Path, output: Path) -> None:
    """Replace ``output`` by ``build_dir``. The old folder is removed afterwards.

    A reader that still has files of the old folder open keeps reading them
    until it closes them, and the server reopens the new build on its next
    request (``CorpusIndex.rebuilt_on_disk``).
    """
    replaced = output.parent / f".{output.name}.replaced-{os.getpid()}"
    os.rename(output, replaced)
    try:
        os.rename(build_dir, output)
    except OSError:
        os.rename(replaced, output)
        raise
    shutil.rmtree(replaced, ignore_errors=True)


def _run_import(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="candy import",
        description=(
            "Import a corpus: build a Fast Index from CSV, JSONL, plain text, "
            "Parquet, VRT, a Hugging Face dataset or paired (pre-aligned) files."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        help="input file, a folder of .txt files for plain text, or a dataset ID for --input-format hf",
    )
    parser.add_argument(
        "--output",
        required=True,
        help=(
            "directory of the corpus index, for example ~/.candyconc/corpora/NAME. "
            "An index already there is replaced when the import has finished"
        ),
    )
    parser.add_argument(
        "--input-format",
        choices=(
            "parquet",
            "vrt",
            "prealigned-parquet",
            "prealigned-csv",
            "prealigned-jsonl",
            "prealigned_parquet",
            "prealigned_csv",
            "prealigned_jsonl",
            "plaintext",
            "csv",
            "jsonl",
            "hf",
        ),
        default=None,
        help=(
            "input format (default: from the file extension: .csv/.tsv csv, "
            ".jsonl/.ndjson jsonl, .txt or a folder plaintext, .parquet parquet, .vrt/.xml vrt)"
        ),
    )
    parser.add_argument(
        "--language",
        default=None,
        help=(
            "ISO 639 code of the corpus language, for example en or de. Selects "
            "the standard spaCy pipeline for it (en: en_core_web_md, de: "
            "de_core_news_md), or blank:<language> when spaCy has no trained one"
        ),
    )
    parser.add_argument(
        "--spacy-model",
        default=None,
        help=(
            "spaCy pipeline for tokenization and annotation, for example "
            "en_core_web_sm or de_core_news_md (install with: candy pipeline <name>), "
            "or blank:<language> for tokenization only (default: the standard "
            "pipeline of --language, without --language de_core_news_md)"
        ),
    )
    parser.add_argument(
        "--batch-size", type=int, default=0, help="texts per spaCy batch (default: 0, chosen from free memory)"
    )
    parser.add_argument(
        "--n-process", type=int, default=0, help="spaCy worker processes (default: 0, chosen from CPU cores)"
    )
    parser.add_argument(
        "--include-prompts",
        action="store_true",
        default=False,
        help="Parquet and VRT: keep the prompt text of generated variants as document metadata",
    )
    parser.add_argument(
        "--enable-ner", action="store_true", default=False, help="add named entities (attribute ent)"
    )
    parser.add_argument(
        "--enable-deps",
        dest="enable_deps",
        action="store_true",
        default=None,
        help=(
            "add dependency relations (attributes rel and head), needed for word sketches. "
            "Default: on when the pipeline has a parser, except VRT annotation adoption"
        ),
    )
    parser.add_argument(
        "--no-deps", dest="enable_deps", action="store_false", help="import without dependency parsing"
    )
    parser.add_argument(
        "--no-split-long-texts",
        dest="split_long_texts",
        action="store_false",
        help="keep texts longer than --max-doc-chars as one document instead of splitting them",
    )
    parser.add_argument(
        "--allow-missing-input-text",
        action="store_true",
        default=False,
        help="Parquet and VRT: accept rows without the input_text column",
    )
    parser.add_argument(
        "--max-doc-chars",
        type=int,
        default=1_000_000,
        help="longer texts are split at paragraph or whitespace boundaries (default: 1000000)",
    )
    parser.add_argument(
        "--meta-index-fields",
        default="",
        help="comma-separated metadata fields for the filter index (default: all fields)",
    )
    parser.add_argument(
        "--no-capture-whitespace",
        dest="capture_whitespace",
        action="store_false",
        default=True,
        help=(
            "do not record the spacing between tokens (whitespace_after.bin). Concordance "
            "lines and texts then show every token separated by a space, for example "
            "\"soul . No\" instead of \"soul. No\""
        ),
    )

    # VRT import options
    parser.add_argument("--segment-tag", default="text", help="VRT: element that becomes one document")
    parser.add_argument("--text-tag", default="text", help="VRT: parent element that carries text metadata")
    parser.add_argument("--sentence-tag", default="s", help="VRT: sentence element")
    parser.add_argument(
        "--source",
        default="",
        help="value of the source metadata field (vrt: used when no source attribute is found)",
    )
    parser.add_argument("--register", default="", help="VRT: fallback value of the register metadata field")
    parser.add_argument(
        "--min-text-chars", type=int, default=1, help="VRT: skip documents with fewer characters"
    )
    parser.add_argument("--variant", default="document", help="VRT: value of the variant metadata field")
    parser.add_argument("--model", default="none", help="VRT: value of the model metadata field")
    parser.add_argument(
        "--token-columns",
        "--columns",
        default="",
        help="VRT: comma-separated names of the token columns, for example word,lemma,pos",
    )
    parser.add_argument(
        "--token-separator",
        choices=("auto", "tab", "whitespace"),
        default="auto",
        help="VRT: separator between token columns",
    )
    parser.add_argument("--word-column", default="word", help="VRT: column (name or number) with the word form")
    parser.add_argument(
        "--strict-columns",
        action="store_true",
        default=False,
        help="VRT: stop at a token line with a different number of columns",
    )
    parser.add_argument(
        "--join-mode",
        choices=("smart", "space"),
        default="smart",
        help="VRT: how tokens are joined into the document text (smart: no space before punctuation)",
    )
    parser.add_argument("--id-attrs", default="", help="VRT: attributes that hold the document ID, comma-separated")
    parser.add_argument("--source-attrs", default="", help="VRT: attributes that hold the source, comma-separated")
    parser.add_argument(
        "--register-attrs", default="", help="VRT: attributes that hold the register, comma-separated"
    )
    parser.add_argument("--date-attrs", default="", help="VRT: attributes that hold the date, comma-separated")
    parser.add_argument("--genre-attrs", default="", help="VRT: attributes that hold the genre, comma-separated")
    parser.add_argument(
        "--annotation-mode",
        choices=("none", "sidecar", "adopt"),
        default="sidecar",
        help="VRT: annotate with spaCy and keep supplied columns separately (sidecar), drop them (none), or index them unchanged (adopt)",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        default=False,
        help="VRT: print what the file contains without building an index",
    )
    parser.add_argument("--inspect-docs", type=int, default=3, help="VRT: documents shown by --inspect")

    # Pre-aligned Parquet/CSV/JSONL import options
    parser.add_argument("--text-column", default="text", help="column with the text")
    parser.add_argument("--id-column", default="id", help="column with the document ID")
    parser.add_argument(
        "--pair-key-column", default="pair_id", help="Paired import: column that groups the variants of one text"
    )
    parser.add_argument(
        "--pair-role-column", default="pair_role", help="Paired import: column with the role of each variant"
    )
    parser.add_argument(
        "--anchor-role", default="source", help="Paired import: role of the variant the others are aligned to"
    )
    parser.add_argument(
        "--pair-axis", default="prealigned", help="Paired import: name of the pairing recorded in the manifest"
    )
    parser.add_argument(
        "--pair-order",
        choices=("unsorted", "grouped", "sorted"),
        default="unsorted",
        help="Paired import: grouped or sorted input streams one group at a time, unsorted keeps all rows in memory",
    )
    parser.add_argument(
        "--meta-columns",
        nargs="*",
        default=None,
        help="columns to keep as document metadata, separated by spaces (default: none)",
    )
    parser.add_argument("--variant-column", default=None, help="Paired import: column with the variant name")
    parser.add_argument(
        "--model-column", default=None, help="Paired import: column with the name of the generating model"
    )
    parser.add_argument("--delimiter", default=None, help="CSV: field separator (default: detected)")
    parser.add_argument(
        "--reject-policy",
        choices=("collect", "fail_fast"),
        default="collect",
        help="collect: skip invalid rows and list them in the rejected rows report, fail_fast: stop at the first one",
    )
    parser.add_argument(
        "--reject-report",
        default=None,
        help=(
            "also write every rejected row to this JSON Lines file "
            "(reject_report.json in the index always lists the counts and up to 50 rows)"
        ),
    )

    # Plaintext-Import options
    parser.add_argument("--pattern", default="*.txt", help="Plain text: file pattern inside the input folder")
    parser.add_argument(
        "--split-paragraphs",
        action="store_true",
        default=False,
        help="Plain text: one document per paragraph instead of one per file",
    )

    # HuggingFace-Import options (--input traegt die Dataset-ID;
    # trust_remote_code bleibt hart deaktiviert und hat bewusst kein Flag)
    parser.add_argument("--hf-config", default=None, help="Hugging Face: dataset configuration")
    parser.add_argument("--hf-split", default="train", help="Hugging Face: dataset split")
    parser.add_argument("--limit", type=int, default=None, help="Hugging Face: import at most this many rows")
    args = parser.parse_args(argv)

    _FORMAT_HELP = (
        "Unknown input format. Use --input-format="
        "parquet|vrt|prealigned-parquet|prealigned-csv|prealigned-jsonl|"
        "plaintext|csv|jsonl|hf."
    )
    input_path = Path(args.input).expanduser()
    ext = input_path.suffix.lower()
    if args.input_format is not None:
        method_key = normalize_import_method(args.input_format)
    elif ext == ".parquet":
        method_key = "parquet"
    elif ext in {".vrt", ".xml"}:
        method_key = "vrt"
    elif ext in {".csv", ".tsv"}:
        method_key = "csv"
    elif ext in {".jsonl", ".ndjson"}:
        method_key = "jsonl"
    elif ext == ".txt" or input_path.is_dir():
        method_key = "plaintext"
    else:
        raise SystemExit(_FORMAT_HELP)

    builder_spec = import_builder_spec(method_key)
    if builder_spec is None:
        raise SystemExit(_FORMAT_HELP)

    # Erststart-Preflight: das spaCy-Modell ist die haeufigste fehlende
    # Voraussetzung. Ohne diesen Check endet der Import erst im Builder mit
    # einem rohen Traceback. Pfade und blank:-Pipelines sind ausgenommen.
    from candyconc.ingest import pipelines as _pipelines

    try:
        spacy_model = _pipelines.resolve_import_pipeline(args.language, args.spacy_model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.language and not args.spacy_model:
        if _pipelines.is_blank(spacy_model):
            print(
                f"spaCy has no trained pipeline for '{_pipelines.normalize_language(args.language)}'. "
                f"Importing with {spacy_model}, which tokenizes without linguistic annotation.",
                file=sys.stderr,
            )
        else:
            print(f"Language {_pipelines.normalize_language(args.language)}: spaCy pipeline {spacy_model}.", file=sys.stderr)
    adopts_annotations = method_key == "vrt" and args.annotation_mode == "adopt"
    if not adopts_annotations and spacy_model and not _pipelines.pipeline_installed(spacy_model):
        raise SystemExit(_pipelines.missing_message(spacy_model))
    enable_deps = args.enable_deps
    if enable_deps is None:
        # Dependencies cost little next to tagging and open Word Sketch and
        # rel/head queries, so a pipeline with a parser uses it by default.
        enable_deps = not adopts_annotations and _pipelines.pipeline_has_parser(spacy_model)
        if enable_deps:
            print(
                f"Dependency parsing is on: {spacy_model} has a parser (--no-deps turns it off).",
                file=sys.stderr,
            )

    # Parquet: an ordinary table (text and metadata columns) imports like CSV.
    # The paired human/AI layout of the research data model (target_text,
    # input_text) keeps its own builder path.
    parquet_generic = False
    if method_key == "parquet":
        parquet_generic = _parquet_layout(
            input_path,
            args.text_column,
            aligned_options=bool(args.include_prompts or args.allow_missing_input_text),
        ) == "generic"
    # DT-PACKAGED-IMPORT: the in-process runner dispatches importable builders
    # without a subprocess (wheel-safe).
    from candyconc.builders import _runner

    try:
        # Resolve the repo-root builder script for the SUBPROCESS FALLBACK
        # path only (used when no importable in-process builder exists — see
        # the dispatch below). CANDYCONC_BUILDER_DIR overrides the walk; the
        # packaged candyconc.builders launchers are the source-tree-walk
        # endpoint. The parquet builder normally runs in-process and never
        # needs this path, so resolution failure here is tolerated for the
        # in-process builders.
        builder = find_builder_script(builder_spec.script_name, start=__file__)
    except FileNotFoundError as exc:
        builder = None
        if builder_spec.script_name not in _runner._INPROCESS_MODULES:
            raise SystemExit(str(exc)) from exc
    subcommand = list(builder_spec.subcommand)
    cli_format_name = method_key.replace("_", "-")

    output_dir = Path(args.output).expanduser()
    if output_dir.is_symlink():
        output_dir = output_dir.resolve()
    inspect_only = method_key == "vrt" and bool(getattr(args, "inspect", False))
    build_dir = None if inspect_only else _replacement_build_dir(output_dir)
    if build_dir is not None:
        shutil.rmtree(build_dir, ignore_errors=True)
        print(
            f"{output_dir} holds a corpus index. The import builds the new index "
            "next to it and replaces the old one when it has finished.",
            file=sys.stderr,
        )
        if args.reject_report:
            report = Path(args.reject_report).expanduser().resolve(strict=False)
            if report.is_relative_to(output_dir.resolve(strict=False)):
                # A report inside the old folder would be removed with it.
                args.reject_report = str(build_dir / report.relative_to(output_dir.resolve(strict=False)))

    cmd = [
        sys.executable,
        str(builder),
        *subcommand,
        "--input",
        str(input_path),
        "--output",
        str(build_dir or output_dir),
        "--spacy-model",
        spacy_model,
        "--max-doc-chars",
        str(args.max_doc_chars),
    ]
    if args.batch_size:
        cmd += ["--batch-size", str(args.batch_size)]
    if args.n_process:
        cmd += ["--n-process", str(args.n_process)]
    if args.include_prompts and method_key in {"parquet", "vrt"}:
        cmd.append("--include-prompts")
    if args.enable_ner:
        cmd.append("--enable-ner")
    if enable_deps:
        cmd.append("--enable-deps")
    if args.allow_missing_input_text and method_key in {"parquet", "vrt"}:
        cmd.append("--allow-missing-input-text")
    if args.meta_index_fields:
        cmd += ["--meta-index-fields", args.meta_index_fields]
    if args.split_long_texts is False:
        cmd.append("--no-split-long-texts")
    if not args.capture_whitespace:
        cmd.append("--no-capture-whitespace")

    if method_key == "vrt":
        cmd += [
            "--segment-tag",
            args.segment_tag,
            "--text-tag",
            args.text_tag,
            "--sentence-tag",
            args.sentence_tag,
            "--source",
            args.source,
            "--register",
            args.register,
            "--min-text-chars",
            str(args.min_text_chars),
            "--variant",
            args.variant,
            "--model",
            args.model,
            "--token-separator",
            args.token_separator,
            "--word-column",
            args.word_column,
            "--join-mode",
            args.join_mode,
            "--annotation-mode",
            args.annotation_mode,
        ]
        if args.token_columns:
            cmd += ["--token-columns", args.token_columns]
        if args.strict_columns:
            cmd.append("--strict-columns")
        if args.id_attrs:
            cmd += ["--id-attrs", args.id_attrs]
        if args.source_attrs:
            cmd += ["--source-attrs", args.source_attrs]
        if args.register_attrs:
            cmd += ["--register-attrs", args.register_attrs]
        if args.date_attrs:
            cmd += ["--date-attrs", args.date_attrs]
        if args.genre_attrs:
            cmd += ["--genre-attrs", args.genre_attrs]
        if args.inspect:
            cmd.append("--inspect")
            cmd += ["--inspect-docs", str(args.inspect_docs)]
    elif method_key in {"prealigned_parquet", "prealigned_csv", "prealigned_jsonl"}:
        cmd += [
            "--text-column",
            args.text_column,
            "--id-column",
            args.id_column,
            "--pair-key-column",
            args.pair_key_column,
            "--pair-role-column",
            args.pair_role_column,
            "--anchor-role",
            args.anchor_role,
            "--pair-axis",
            args.pair_axis,
            "--pair-order",
            args.pair_order,
            "--source",
            args.source or f"{cli_format_name}-import",
            "--reject-policy",
            args.reject_policy,
        ]
        if args.meta_columns:
            cmd += ["--meta-columns", *args.meta_columns]
        if args.variant_column:
            cmd += ["--variant-column", args.variant_column]
        if args.model_column:
            cmd += ["--model-column", args.model_column]
        if args.reject_report:
            cmd += ["--reject-report", args.reject_report]
        if method_key == "prealigned_csv" and args.delimiter:
            cmd += ["--delimiter", args.delimiter]
    elif method_key in {"csv", "jsonl", "hf"} or parquet_generic:
        if parquet_generic:
            cmd += ["--generic", "--source", args.source or "parquet-import"]
        cmd += [
            "--text-column",
            args.text_column,
            "--reject-policy",
            args.reject_policy,
        ]
        if args.id_column:
            cmd += ["--id-column", args.id_column]
        if args.meta_columns:
            cmd += ["--meta-columns", *args.meta_columns]
        if args.source and not parquet_generic:
            cmd += ["--source", args.source]
        if args.reject_report:
            cmd += ["--reject-report", args.reject_report]
        if method_key == "csv" and args.delimiter:
            cmd += ["--delimiter", args.delimiter]
        if method_key == "hf":
            # --input traegt die Dataset-ID (Alias fuer --dataset im Adapter);
            # trust_remote_code bleibt hart deaktiviert (kein Flag).
            cmd += ["--split", args.hf_split]
            if args.hf_config:
                cmd += ["--config", args.hf_config]
            if args.limit is not None:
                cmd += ["--limit", str(args.limit)]
    elif method_key == "plaintext":
        cmd += [
            "--pattern",
            args.pattern,
            "--reject-policy",
            args.reject_policy,
        ]
        if args.split_paragraphs:
            cmd.append("--split-paragraphs")
        if args.source:
            cmd += ["--source", args.source]
        if args.reject_report:
            cmd += ["--reject-report", args.reject_report]

    # DT-PACKAGED-IMPORT: run the builder IN-PROCESS when its implementation
    # module is importable (wheel-safe — no subprocess, no repo-root
    # dependency). ``cmd`` is [python, builder_path, *builder_argv]; the
    # in-process runner only needs the script_name + builder_argv. It returns
    # ``None`` when no importable module exists, in which case we fall back to
    # the resolved builder script as a subprocess (source-checkout path).
    builder_argv = list(cmd[2:])
    try:
        rc = _runner.run_in_process(builder_spec.script_name, builder_argv)
        if rc is None:
            if builder is None:
                raise SystemExit(
                    f"Builder {builder_spec.script_name!r} can be found neither as "
                    "an in-process module nor as a scripts/jobs script."
                )
            proc = subprocess.run(cmd, check=False)
            rc = proc.returncode
    except BaseException:
        if build_dir is not None:
            shutil.rmtree(build_dir, ignore_errors=True)
            print(f"The import failed. The corpus in {output_dir} is unchanged.", file=sys.stderr)
        raise
    if rc != 0:
        if build_dir is not None:
            shutil.rmtree(build_dir, ignore_errors=True)
            print(f"The import failed. The corpus in {output_dir} is unchanged.", file=sys.stderr)
        raise SystemExit(rc)
    if build_dir is not None:
        if not has_index(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)
            raise SystemExit(
                f"The import finished without a complete index. The corpus in {output_dir} is unchanged."
            )
        _swap_in_index(build_dir, output_dir)
        print(f"Replaced the corpus index in {output_dir}", file=sys.stderr)
    return


_COMMANDS_HELP = """commands:
  (none)            start the server and the web interface (options above)
  import            import a corpus: candy import --input FILE --output DIR ...
  pipeline NAME     download and install a spaCy pipeline, e.g. en_core_web_sm
  paths             show where CandyConc keeps data and reads its configuration
  migrate-project   migrate a legacy .ccproj project file

Run "candy <command> --help" for the options of a command.
"""

_DEFAULT_PORT = 8010
#: Without an explicit --port, the next free port in this range is used.
_PORT_SEARCH = 20


def _version_text() -> str:
    from candyconc.version import package_version

    return f"CandyConc {package_version()} (Python {sys.version.split()[0]})"


def _run_pipeline(argv: list[str]) -> None:
    from candyconc.ingest import pipelines
    from candyconc.paths import pipelines_dir

    parser = argparse.ArgumentParser(
        prog="candy pipeline",
        description=(
            "Download and install a spaCy pipeline from GitHub (explosion/spacy-models). "
            "CandyConc never downloads pipelines by itself."
        ),
    )
    parser.add_argument("name", help="pipeline package, e.g. en_core_web_sm, de_core_news_md")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--target", type=Path, help="install into this directory instead of the Python environment")
    target.add_argument(
        "--user-dir",
        action="store_true",
        help=f"install into the CandyConc data directory ({pipelines_dir()})",
    )
    parser.add_argument("--print-url", action="store_true", help="only print the download URL")
    args = parser.parse_args(argv)
    if pipelines.is_blank(args.name):
        print(f"{args.name} needs no download.")
        return
    try:
        url = pipelines.download_url(args.name)
    except Exception as exc:
        raise SystemExit(f"No spaCy pipeline {args.name!r} found for this spaCy version: {exc}") from exc
    if args.print_url:
        print(url)
        return
    destination = pipelines_dir() if args.user_dir else args.target
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
    cmd = pipelines.install_command(url, target=destination)
    print(f"Downloading spaCy pipeline {args.name} from {url}", flush=True)
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        raise SystemExit(rc)
    where = destination if destination is not None else Path(sys.prefix)
    print(f"Installed {args.name} into {where}.")


def _print_paths() -> None:
    from candyconc import paths

    width = 18
    for key, value in paths.describe().items():
        print(f"{key.replace('_', ' '):<{width}} {value}")


def _port_free(host: str, port: int) -> bool:
    import socket

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _choose_port(host: str, requested: int | None) -> int:
    if requested is not None:
        if not _port_free(host, requested):
            raise SystemExit(f"Port {requested} on {host} is already in use. Choose another one with --port.")
        return requested
    for port in range(_DEFAULT_PORT, _DEFAULT_PORT + _PORT_SEARCH):
        if _port_free(host, port):
            return port
    raise SystemExit(
        f"Ports {_DEFAULT_PORT} to {_DEFAULT_PORT + _PORT_SEARCH - 1} are in use. Choose one with --port."
    )


def _open_browser_when_ready(url: str, health_url: str) -> None:
    import threading
    import time
    import urllib.request
    import webbrowser

    def _wait_and_open() -> None:
        for _ in range(600):
            try:
                with urllib.request.urlopen(health_url, timeout=2):
                    break
            except Exception:
                time.sleep(0.5)
        else:
            return
        webbrowser.open(url)

    threading.Thread(target=_wait_and_open, name="candy-open-browser", daemon=True).start()


def _startup_corpus_text() -> str:
    """Which corpus the server will open, for the start banner."""
    from candyconc.domain.corpus import CorpusRegistry

    env_index = os.environ.get("CANDYCONC_INDEX_PATH")
    if env_index:
        return f"{env_index} (CANDYCONC_INDEX_PATH)"
    cfg_index = load_settings().index_dir
    if cfg_index:
        return f"{cfg_index} (index_dir)"
    registry = CorpusRegistry.load()
    if registry.active and has_index(Path(registry.active)):
        return f"{registry.active} (active in the catalog)"
    from candyconc.domain.corpus import ready_corpora_newest_first
    from candyconc.paths import corpora_dir

    newest = ready_corpora_newest_first(corpora_dir())
    if newest:
        return f"{newest[0]} (most recent corpus, will be activated)"
    return "none yet. Import one in the web interface (Corpora) or with: candy import --help"


def _serve(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="candy",
        description="CandyConc: corpus analysis in the browser. Starts the server and the web interface.",
        epilog=_COMMANDS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=_version_text())
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "bind address (default: 127.0.0.1, loopback only). "
            "A network address such as 0.0.0.0 is refused in the default "
            "single-user mode. Use it with CANDYCONC_SECURITY_MODE=release "
            "and --enable-rbac."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port (default: {_DEFAULT_PORT}, or the next free one when it is taken)",
    )
    parser.add_argument("--open", action="store_true", help="open the web interface in the browser")
    parser.add_argument(
        "--enable-rbac",
        action="store_true",
        help="enforce role-based access control",
    )
    parser.add_argument("--log-level", help="log level, for example DEBUG or WARNING (default: INFO)")
    parser.add_argument("--log-file", help="also write the log to this file")
    args = parser.parse_args(argv)
    from candyconc.config import APP_CONFIG
    from candyconc.config import set as set_config

    if args.enable_rbac:
        set_config("CANDYCONC_ENABLE_RBAC", "1")
    # Route log flags through config.set() (single-source). It write-throughs to
    # os.environ for any call-time consumers and updates APP_CONFIG so
    # init_logging() observes the override.
    if args.log_level:
        set_config("CANDYCONC_LOG_LEVEL", args.log_level)
    if args.log_file:
        set_config("CANDYCONC_LOG_FILE", args.log_file)
    init_logging()
    _enforce_network_bind_security(args.host)
    port = _choose_port(args.host, args.port)
    # K1: Die REST-nutzenden Tool-Wrapper (und ein explizit konfigurierter
    # Remote-MCP-Fallback) lesen CANDYCONC_BACKEND_URL. Ohne diesen Default
    # sterben auf einem Nicht-Standard-Port alle REST-Wrapper mit einem
    # opaken Verbindungsfehler gegen :8010. Der Default folgt dem realen
    # Bind. Herkunfts-Erkennung: der AUSGELIEFERTE Default-Wert gilt als
    # "nicht kundenspezifisch" und wird auf den realen Bind korrigiert;
    # jeder davon abweichende (explizit gesetzte) Wert gewinnt.
    from candyconc.config import get as get_config

    _shipped_backend_url = "http://127.0.0.1:8010/api/v1"
    bind_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    current_backend_url = str(get_config("CANDYCONC_BACKEND_URL", "") or "").strip()
    if not current_backend_url or current_backend_url == _shipped_backend_url:
        set_config("CANDYCONC_BACKEND_URL", f"http://{bind_host}:{port}/api/v1")
    # A configured pin must point at a valid index. Without a pin the server
    # opens the active catalog corpus or starts with an empty catalog.
    env_index = os.environ.get("CANDYCONC_INDEX_PATH")
    tmp_root = Path(tempfile.gettempdir()).resolve()
    candidates: list[Path] = []
    if env_index:
        candidates.append(Path(env_index))
    cfg_index = load_settings().index_dir
    if cfg_index:
        candidates.append(Path(cfg_index))
    for p in candidates:
        resolved = p.expanduser().resolve()
        if tmp_root in resolved.parents or resolved == tmp_root:
            raise SystemExit(f"A temporary index is not allowed: {resolved}")
        if not has_index(resolved):
            raise SystemExit(f"No valid index path found: {p}")
    # S5b Single-Command-Start: ein klarer Hinweis, ob die Web-UI mit
    # ausgeliefert wird (gebautes Frontend gefunden) oder nur die API läuft.
    from candyconc.paths import data_dir
    from candyconc.services.backend.frontend_static import frontend_dist_dir

    url = f"http://{bind_host}:{port}/"
    frontend_dist = frontend_dist_dir()
    print(_version_text())
    if frontend_dist is not None:
        print(f"  Web interface: {url}")
    else:
        print(f"  API only at {url}api/v1 (no built web interface found; see packaging/build_web.py)")
    print(f"  Corpus: {_startup_corpus_text()}")
    print(f"  Data: {data_dir()}")
    if APP_CONFIG.copilot_configured:
        print(f"  Copilot: {APP_CONFIG.COPILOT_MODEL} at {APP_CONFIG.COPILOT_ENDPOINT}")
    else:
        print("  Copilot: no language model configured (optional, see Settings > Model connection)")
    print("Press Ctrl+C to stop.", flush=True)
    if args.open and frontend_dist is not None:
        _open_browser_when_ready(url, f"http://{bind_host}:{port}/api/v1/health")
    uvicorn.run("candyconc.services.backend.server:app", host=args.host, port=port)


def main() -> None:
    argv = sys.argv[1:]
    command = argv[0] if argv else ""
    if command == "migrate-project":
        _migrate_project(argv[1:])
        return
    if command == "import":
        _run_import(argv[1:])
        return
    if command == "pipeline":
        _run_pipeline(argv[1:])
        return
    if command == "paths":
        _print_paths()
        return
    if command == "serve":
        argv = argv[1:]
    _serve(argv)


if __name__ == "__main__":  # pragma: no cover - CLI
    main()

__all__ = ["main"]
