"""Lightweight wrapper for the C search library."""

from __future__ import annotations

import ctypes
from pathlib import Path


_lib = None


def _load_lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        lib_path = Path(__file__).with_name("libsearch.so")
        if not lib_path.exists():
            raise RuntimeError("libsearch.so not built")
        _lib = ctypes.CDLL(str(lib_path))
    return _lib


def document_search(db_path: str, term: str, bufsize: int = 4096) -> str:
    """Return results from :func:`cc_document_search` as JSON."""

    lib = _load_lib()
    buf = ctypes.create_string_buffer(bufsize)
    rc = lib.cc_document_search(db_path.encode(), term.encode(), buf, len(buf))
    if rc != 0:
        raise RuntimeError("cc_document_search failed")
    return buf.value.decode()


__all__ = ["document_search"]
