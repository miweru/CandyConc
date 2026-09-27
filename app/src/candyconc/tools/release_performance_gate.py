from __future__ import annotations

import argparse
import csv
import importlib
import json
import time
from io import StringIO
from pathlib import Path
from typing import Any, Callable


GateResult = dict[str, Any]


def _measure(name: str, fn: Callable[[], dict[str, Any] | None]) -> GateResult:
    start = time.perf_counter()
    try:
        detail = fn() or {}
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "name": name,
            "status": "passed",
            "duration_ms": round(duration_ms, 3),
            **detail,
        }
    except Exception as exc:  # pragma: no cover - exercised by release CLI
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "name": name,
            "status": "failed",
            "duration_ms": round(duration_ms, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _csv_export_smoke(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure browser-export-like CSV serialization, not Pandoc PDF/DOCX."""

    out = StringIO()
    if rows:
        fieldnames = sorted({key for row in rows for key in row})
    else:
        fieldnames = ["status"]
        rows = [{"status": "no_rows"}]
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return {
        "rows": len(rows),
        "bytes": len(out.getvalue().encode("utf-8")),
        "scope": "csv_serialization_only_pdf_docx_pandoc_not_measured",
    }


def _native_extension_probe(missing: dict[str, Exception] | None = None) -> dict[str, Any]:
    if missing is None:
        from candyconc.core.native_extensions import missing_native_extensions

        missing = missing_native_extensions()
    if missing:
        names = sorted(str(name) for name in missing)
        raise RuntimeError(
            "Native Extensions fehlen; Performance-Release-Gate darf nicht grün "
            f"werden: {', '.join(names)}"
        )
    return {
        "scope": "backend_module_import_and_native_extension_probe",
        "native_extensions": "available",
        "missing_native_extensions": [],
    }


def run_gate(index_path: Path, *, term: str, limit: int = 50) -> dict[str, Any]:
    results: list[GateResult] = []
    kwic_rows: list[dict[str, Any]] = []
    idx_holder: dict[str, Any] = {}

    def startup() -> dict[str, Any]:
        importlib.import_module("candyconc.services.backend.server")
        return _native_extension_probe()

    def corpus_load() -> dict[str, Any]:
        from candyconc.core.corpus_index import CorpusIndex

        idx = CorpusIndex(index_path, read_only=True)
        idx_holder["idx"] = idx
        return {
            "scope": "CorpusIndex_read_only_open",
            "index_path": str(index_path),
        }

    def kwic() -> dict[str, Any]:
        from candyconc.core.query_runtime import run_query

        idx = idx_holder["idx"]
        rows = list(run_query(term, ctx=5, corpus=idx, limit=limit))
        kwic_rows[:] = rows
        if not rows:
            raise RuntimeError(f"KWIC gate produced no rows for term {term!r}")
        return {
            "scope": "KWIC_first_page_exactness_not_claimed_by_this_gate",
            "term": term,
            "rows": len(rows),
            "limit": limit,
        }

    def autocomplete() -> dict[str, Any]:
        from candyconc.core.cql_engine import analyse_cql_backend

        idx = idx_holder["idx"]
        query = f'cql:[word="{term[:1]}'
        response = analyse_cql_backend(idx.fast_index, query, limit=20)
        suggestions = response.get("suggestions") or []
        return {
            "scope": "CQL_autocomplete_language_service",
            "query": query,
            "suggestions": len(suggestions),
        }

    def export_csv() -> dict[str, Any]:
        return _csv_export_smoke(kwic_rows[:limit])

    try:
        for name, fn in (
            ("startup", startup),
            ("corpus_load", corpus_load),
            ("kwic", kwic),
            ("autocomplete", autocomplete),
            ("export_csv", export_csv),
        ):
            results.append(_measure(name, fn))
    finally:
        idx = idx_holder.get("idx")
        if idx is not None:
            close = getattr(idx, "close", None)
            if callable(close):
                close()

    passed = all(result.get("status") == "passed" for result in results)
    return {
        "status": "passed" if passed else "failed",
        "claim_contract": (
            "This gate proves only that the measured release paths execute on "
            "the selected index. It does not justify broad native/multithreaded "
            "or large-corpus latency claims."
        ),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run small CandyConc release performance smoke gates."
    )
    parser.add_argument("--index", required=True, type=Path, help="Fast Index directory")
    parser.add_argument("--term", default="der", help="KWIC term known to exist in the index")
    parser.add_argument("--limit", default=50, type=int, help="KWIC/export row limit")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    result = run_gate(args.index, term=args.term, limit=max(1, args.limit))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"release performance gate: {result['status']}")
        for item in result["results"]:
            print(
                f"- {item['name']}: {item['status']} "
                f"({item['duration_ms']} ms) {item.get('scope', '')}"
            )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
