from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable, Optional

import httpx

from candyconc.paths import data_dir  # noqa: E402

# Downloaded embedding packages live with the user data, never inside the
# installed package.
EMB_DIR = Path(os.environ.get("CANDYCONC_EMB_DIR", data_dir() / "embeddings"))

MAX_EMBEDDING_BYTES = 500 * 1024 * 1024  # hard ceiling regardless of confirm


def _safe_dest(name: str) -> Path:
    """Resolve ``<EMB_DIR>/<name>.txt`` rejecting any traversal in ``name``."""
    from candyconc.domain.corpus import normalize_corpus_name

    safe = normalize_corpus_name(name)
    dest = EMB_DIR / f"{safe}.txt"
    dest.resolve().relative_to(EMB_DIR.resolve())  # raises ValueError on escape
    return dest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_digest(path: Path, expected_sha256: str) -> None:
    if _sha256_file(path) != expected_sha256:
        raise ValueError("checksum mismatch")


async def download_embedding(
    name: str,
    url: str,
    sha256: str,
    *,
    confirm: Optional[Callable[[int], bool]] = None,
    allow_file_url: bool = False,
) -> Path:
    """Download ``url`` into the vendor embeddings folder and verify checksum.

    ``name`` is validated to a single safe path segment. ``file://`` URLs are
    rejected unless ``allow_file_url=True`` (off for the server-exposed path, so it
    can never read arbitrary local files). A file larger than
    ``MAX_EMBEDDING_BYTES`` is refused unless ``confirm`` explicitly approves it.
    """
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    dest = _safe_dest(name)
    expected_sha256 = (sha256 or "").strip().lower()
    if not expected_sha256:
        raise ValueError("sha256 is required for embedding downloads")
    if dest.exists():
        _verify_digest(dest, expected_sha256)
        return dest

    def _check_size(size: int) -> None:
        if size > MAX_EMBEDDING_BYTES:
            if confirm is None or not confirm(size):
                raise RuntimeError(
                    f"Embedding-Download {size} Bytes überschreitet das Limit "
                    f"({MAX_EMBEDDING_BYTES} Bytes)."
                )

    digest = hashlib.sha256()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=EMB_DIR,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            total = 0

            def _write_chunk(chunk: bytes) -> None:
                nonlocal total
                if not chunk:
                    return
                total += len(chunk)
                _check_size(total)
                digest.update(chunk)
                tmp.write(chunk)

            if url.startswith("file://"):
                if not allow_file_url:
                    raise ValueError("file:// URLs sind hier nicht erlaubt.")
                file_path = Path(url[7:])
                _check_size(file_path.stat().st_size)  # check BEFORE reading
                with file_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        _write_chunk(chunk)
            elif url.startswith(("http://", "https://")):
                async with httpx.AsyncClient() as client:
                    try:
                        head = await client.head(url)
                        head.raise_for_status()
                        size = int(head.headers.get("Content-Length", "0"))
                    except Exception:
                        size = 0
                    _check_size(size)
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            _write_chunk(chunk)
            else:
                raise ValueError("Nur http(s):// URLs werden unterstützt.")

        if digest.hexdigest() != expected_sha256:
            raise ValueError("checksum mismatch")
        os.replace(tmp_path, dest)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return dest


def load_embedding(name: str) -> dict[str, list[float]]:
    """Load embeddings from ``name`` package into a word -> vector mapping."""
    path = _safe_dest(name)
    if not path.exists():
        raise FileNotFoundError(path)

    mapping: dict[str, list[float]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            word = parts[0]
            vec = [float(p) for p in parts[1:]]
            mapping[word] = vec
    return mapping


__all__ = ["download_embedding", "load_embedding", "EMB_DIR"]
