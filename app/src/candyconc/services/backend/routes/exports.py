"""Export artifact routes for generated files and Markdown conversions."""

from __future__ import annotations

import asyncio
import functools
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Annotated, Dict

from fastapi import Body, Depends, HTTPException
from fastapi.responses import FileResponse

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import lt

from .. import auth

router = CandyAPIRouter()


def _server():
    from .. import server as _backend_server

    return _backend_server


def _pandoc_supports_sandbox() -> bool:
    try:
        out = subprocess.run(
            ["pandoc", "--help"],
            check=True,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        return False
    return "--sandbox" in (out.stdout or "")


@functools.lru_cache(maxsize=1)
def _pdf_engine() -> str:
    """Best available PDF engine. xelatex/lualatex are Unicode-capable and
    do not crash on emoji/symbols (a missing glyph is a warning, not a fatal
    error); pdflatex is the non-Unicode fallback."""
    for engine in ("xelatex", "lualatex", "pdflatex"):
        if shutil.which(engine):
            return engine
    return "pdflatex"


def _sanitize_for_pdflatex(text: str) -> str:
    """pdflatex aborts on codepoints it cannot encode (non-BMP / emoji).
    Replace them with a VISIBLE bracketed marker so content is preserved,
    not silently dropped. Only used on the PDF path when no Unicode engine
    is installed."""
    return "".join(
        ch if ord(ch) <= 0xFFFF else f"[U+{ord(ch):04X}]" for ch in text
    )


async def _pandoc_convert(text: str, ext: str, source_ext: str = ".md") -> Path:
    srv = _server()
    fid = f"{uuid.uuid4().hex}{ext}"
    out_path = srv._EXPORT_DIR / fid
    src_path = out_path.with_suffix(source_ext)

    cmd: list = ["pandoc", src_path]
    if source_ext == ".md":
        cmd += ["-f", "markdown-raw_tex"]
    if _pandoc_supports_sandbox():
        cmd.append("--sandbox")
    if ext == ".pdf":
        engine = _pdf_engine()
        if engine in ("xelatex", "lualatex"):
            cmd.append(f"--pdf-engine={engine}")
        else:
            # Only pdflatex available: sanitize emoji it cannot encode so the
            # run produces a valid PDF instead of crashing. PDF path only.
            text = _sanitize_for_pdflatex(text)
    cmd += ["-o", out_path]

    if not srv.DRY_RUN:
        src_path.write_text(text, encoding="utf-8")
        try:
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                check=True,
                timeout=srv._PANDOC_TIMEOUT_SEC,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise RuntimeError("Pandoc fehlt oder hat Fehler geliefert. Export abgebrochen.") from exc

    return out_path


# Media types by export-file extension. The download route must describe the
# file it actually serves instead of declaring everything text/markdown named
# "clusters.md" (audit honesty fix).
_DOWNLOAD_MEDIA_TYPES: Dict[str, str] = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".tex": "text/x-tex",
    ".txt": "text/plain",
}
_DOWNLOAD_FALLBACK_MEDIA_TYPE = "application/octet-stream"


def _download_media_type(path: Path) -> str:
    return _DOWNLOAD_MEDIA_TYPES.get(path.suffix.lower(), _DOWNLOAD_FALLBACK_MEDIA_TYPE)


@router.get("/download/{file_id}")
async def download_file(
    file_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
):
    """Return an exported file with media type derived from its extension."""
    export_dir = _server()._EXPORT_DIR.resolve()
    path = (export_dir / file_id).resolve()
    try:
        path.relative_to(export_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    # FileResponse derives the Content-Disposition attachment header from
    # ``filename``; the served name is the real file name, not a hard-coded
    # "clusters.md" for arbitrary payloads.
    return FileResponse(
        path,
        media_type=_download_media_type(path),
        filename=path.name,
    )


def _reject_conversion_under_dry_run() -> None:
    """Fail honestly under DRY_RUN.

    ``_pandoc_convert`` skips writing under DRY_RUN, so building a
    FileResponse afterwards would point at a file that was never created and
    surface as a misleading 500. Reject BEFORE any conversion with a clean
    RFC-7807 detail instead.
    """
    if _server().DRY_RUN:
        raise ApiError(
            501,
            "export.dry_run_disabled",
            lt("Export im DRY_RUN-Modus deaktiviert", "Export is disabled in DRY_RUN mode"),
        )


@router.post("/export/pdf")
async def export_pdf_endpoint(
    payload: Dict[str, str] = Body(
        ...,
        examples={"basic": {"summary": "PDF Export", "value": {"markdown": "# Titel\nText"}}},
    ),
):
    """Convert Markdown to PDF via pandoc."""
    text = payload.get("markdown", "")
    if not isinstance(text, str) or not text:
        raise HTTPException(status_code=400, detail="Missing markdown")
    _reject_conversion_under_dry_run()

    try:
        path = await _pandoc_convert(text, ".pdf")
    except RuntimeError as exc:
        raise ApiError(
            502, "export.pdf_failed", lt("PDF-Konvertierung fehlgeschlagen", "PDF conversion failed")
        ) from exc
    return FileResponse(path, media_type="application/pdf", filename="export.pdf")


@router.post("/export/docx")
async def export_docx_endpoint(
    payload: Dict[str, str] = Body(
        ...,
        examples={"basic": {"summary": "DOCX Export", "value": {"markdown": "# Titel\nText"}}},
    ),
):
    """Convert Markdown to DOCX via pandoc."""
    text = payload.get("markdown", "")
    if not isinstance(text, str) or not text:
        raise HTTPException(status_code=400, detail="Missing markdown")
    _reject_conversion_under_dry_run()

    try:
        path = await _pandoc_convert(text, ".docx")
    except RuntimeError as exc:
        raise ApiError(
            502, "export.docx_failed", lt("DOCX-Konvertierung fehlgeschlagen", "DOCX conversion failed")
        ) from exc
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="export.docx",
    )
