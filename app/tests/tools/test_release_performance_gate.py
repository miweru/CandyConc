from __future__ import annotations

import pytest

from candyconc.tools.release_performance_gate import _csv_export_smoke, _native_extension_probe


def test_csv_export_smoke_is_scoped_and_does_not_claim_pandoc() -> None:
    result = _csv_export_smoke(
        [
            {"left": "ein", "kw": "Hase", "right": "läuft"},
            {"left": "der", "kw": "Hase", "right": "springt"},
        ]
    )

    assert result["rows"] == 2
    assert result["bytes"] > 0
    assert result["scope"] == "csv_serialization_only_pdf_docx_pandoc_not_measured"


def test_native_extension_probe_fails_gate_when_required_extensions_are_missing() -> None:
    with pytest.raises(RuntimeError, match="Performance-Release-Gate darf nicht grün"):
        _native_extension_probe({"candyconc.core._fast_count": ImportError("missing")})


def test_native_extension_probe_reports_available_when_required_extensions_load() -> None:
    result = _native_extension_probe({})

    assert result["native_extensions"] == "available"
    assert result["missing_native_extensions"] == []
