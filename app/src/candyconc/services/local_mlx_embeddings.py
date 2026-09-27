"""Managed query-vector process for locally built MLX semantic indexes."""

from __future__ import annotations

import atexit
import json
import selectors
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from candyconc.services.semantic_index_jobs import MODEL_NAME, runtime_python_path


class _ManagedMlxProcess:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: Any = None

    @staticmethod
    def _worker_path() -> Path:
        return Path(__file__).resolve().parents[1] / "tools" / "semantic_mlx_worker.py"

    @staticmethod
    def _read_json_line(process: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
        if process.stdout is None:
            raise RuntimeError("MLX-Worker hat keinen Ausgabekanal")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("MLX-Worker antwortet nicht")
                if not selector.select(remaining):
                    raise TimeoutError("MLX-Worker antwortet nicht")
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError("MLX-Worker wurde unerwartet beendet")
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    return value
        finally:
            selector.close()

    def _stop_unlocked(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _start_unlocked(self, model: str) -> subprocess.Popen[str]:
        python = runtime_python_path()
        if not python.is_file():
            raise RuntimeError(
                "Die lokale MLX-Laufzeit fehlt. Erstelle den semantischen Index "
                "über Einstellungen > Embeddings."
            )
        worker = self._worker_path()
        if not worker.is_file():
            raise RuntimeError("CandyConc MLX-Worker fehlt")
        from candyconc.paths import logs_dir

        log_path = logs_dir() / "mlx-query.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            [str(python), str(worker), "query-server", "--model", model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log_handle,
            text=True,
            bufsize=1,
            close_fds=True,
        )
        ready = self._read_json_line(process, timeout=180)
        if ready.get("status") != "ready":
            process.terminate()
            raise RuntimeError(f"MLX-Worker konnte nicht starten: {ready}")
        self._process = process
        return process

    def embed(self, texts: Sequence[str], *, model: str = MODEL_NAME) -> np.ndarray:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._stop_unlocked()
                process = self._start_unlocked(model)
            if process.stdin is None:
                raise RuntimeError("MLX-Worker hat keinen Eingabekanal")
            request_id = uuid.uuid4().hex
            request = {"id": request_id, "input": [str(text) for text in texts]}
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                response = self._read_json_line(process, timeout=120)
            except Exception:
                self._stop_unlocked()
                raise
            if response.get("id") != request_id:
                self._stop_unlocked()
                raise RuntimeError("MLX-Worker lieferte eine fremde Antwort")
            if response.get("error"):
                raise RuntimeError(str(response["error"]))
            vectors = np.asarray(response.get("data"), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(texts):
                raise RuntimeError("MLX-Worker lieferte eine ungültige Vektorform")
            return vectors

    def stop(self) -> None:
        with self._lock:
            self._stop_unlocked()


_PROCESS = _ManagedMlxProcess()
atexit.register(_PROCESS.stop)


def embed_local_mlx(
    texts: Sequence[str] | str,
    *,
    model: str = MODEL_NAME,
) -> np.ndarray:
    values = [texts] if isinstance(texts, str) else list(texts)
    if not values:
        return np.zeros((0, 0), dtype=np.float32)
    return _PROCESS.embed([str(value) for value in values], model=model)


def stop_local_mlx_worker() -> None:
    _PROCESS.stop()


__all__ = ["embed_local_mlx", "stop_local_mlx_worker"]
