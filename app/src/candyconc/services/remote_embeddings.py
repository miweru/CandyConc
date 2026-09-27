from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from urllib.error import HTTPError
from typing import Iterable, Sequence

import numpy as np

logger = logging.getLogger(__name__)


def _batched(items: Sequence[str], batch_size: int) -> Iterable[list[str]]:
    if batch_size <= 0:
        yield list(items)
        return
    for i in range(0, len(items), int(batch_size)):
        yield list(items[i : i + int(batch_size)])


def embed_remote(
    texts: Sequence[str] | str,
    *,
    endpoint: str,
    model: str,
    batch_size: int = 32,
    timeout: float = 60.0,
) -> np.ndarray:
    if isinstance(texts, str):
        texts = [texts]
    items = [str(t) for t in texts if t is not None]
    if not items:
        return np.zeros((0, 0), dtype=np.float32)
    results: list[list[float]] = []
    retries = int(os.environ.get("CANDYCONC_EMB_RETRIES", "3") or 3)
    base_backoff = float(os.environ.get("CANDYCONC_EMB_BACKOFF", "0.5") or 0.5)
    max_backoff = float(os.environ.get("CANDYCONC_EMB_BACKOFF_MAX", "8") or 8)
    for chunk in _batched(items, int(batch_size)):
        payload = {"model": model, "input": chunk}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
                    raw = resp.read().decode("utf-8")
                break
            except Exception as exc:
                retryable = True
                if isinstance(exc, HTTPError):
                    if 400 <= exc.code < 500 and exc.code != 429:
                        retryable = False
                if not retryable or attempt >= retries:
                    raise RuntimeError(f"Embedding request failed: {exc}") from exc
                sleep_s = min(max_backoff, base_backoff * (2**attempt))
                attempt += 1
                logger.warning(
                    "Embedding request failed (attempt %d/%d): %s. Retry in %.1fs",
                    attempt,
                    retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            raise RuntimeError("Embedding response JSON invalid") from exc
        if isinstance(parsed, dict) and parsed.get("error"):
            raise RuntimeError(f"Embedding error: {parsed.get('error')}")
        data_rows = None
        if isinstance(parsed, dict):
            data_rows = parsed.get("data") or parsed.get("embeddings")
        if not isinstance(data_rows, list):
            raise RuntimeError("Embedding response missing data")
        if data_rows and isinstance(data_rows[0], dict) and "embedding" in data_rows[0]:
            if "index" in data_rows[0]:
                data_rows = sorted(data_rows, key=lambda r: int(r.get("index", 0)))
            embeddings = [row.get("embedding") for row in data_rows]
        else:
            embeddings = data_rows
        if len(embeddings) != len(chunk):
            raise RuntimeError("Embedding response size mismatch")
        for emb in embeddings:
            if emb is None:
                raise RuntimeError("Embedding response contains empty vector")
            results.append(list(emb))
    arr = np.asarray(results, dtype=np.float32)
    if arr.ndim != 2:
        raise RuntimeError("Embedding response has invalid shape")
    return arr


__all__ = ["embed_remote"]
