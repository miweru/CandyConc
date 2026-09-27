from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any, Callable, Coroutine, Dict


logger = logging.getLogger(__name__)


class TaskManager:
    """Schedule background tasks and report progress."""

    def __init__(self) -> None:
        self._jobs: Dict[str, asyncio.Task] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._listeners: list[asyncio.Queue] = []
        self._start_times: Dict[str, float] = {}
        self._log_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Listener management
    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(q)

    def _notify(self, job_id: str, data: Dict[str, Any]) -> None:
        for q in list(self._listeners):
            loop = getattr(q, "_loop", None)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, {"id": job_id, **data})
            else:
                q.put_nowait({"id": job_id, **data})

    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Dict[str, Any]]:
        return self._status

    async def add(self, func: Callable[..., Coroutine[Any, Any, None]] | Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        self._status[job_id] = {"progress": 0, "status": "queued"}

        async def runner() -> None:
            self._status[job_id] = {"progress": 0, "status": "running"}
            self._start_times[job_id] = asyncio.get_running_loop().time()
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(self._progress_cb(job_id), *args, **kwargs)
                else:
                    await asyncio.to_thread(func, *args, **kwargs)
                self._status[job_id] = {"progress": 100, "status": "done"}
            except Exception as exc:  # pragma: no cover - background errors
                logger.exception("Task %s fehlgeschlagen: %s", job_id, exc)
                self._status[job_id] = {"progress": 100, "status": f"error: {exc}"}
            finally:
                self._start_times.pop(job_id, None)
                self._notify(job_id, self._status[job_id])

        self._jobs[job_id] = asyncio.create_task(runner())
        return job_id

    def _progress_cb(self, job_id: str) -> Callable[[int, str], None]:
        def _cb(progress: int, msg: str) -> None:
            self._status[job_id] = {"progress": progress, "status": msg}
            self._notify(job_id, self._status[job_id])

        return _cb

    async def start(self, interval: float = 60.0) -> None:
        """Start periodic logging of running tasks."""
        if self._log_task is None or self._log_task.done():
            self._log_task = asyncio.create_task(self._logger(interval))

    async def stop(self) -> None:
        """Stop the logging task."""
        if self._log_task is not None:
            self._log_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._log_task
            self._log_task = None

    async def _logger(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            now = asyncio.get_running_loop().time()
            for job_id, start in list(self._start_times.items()):
                info = self._status.get(job_id, {})
                status = str(info.get("status", ""))
                if status != "done" and not status.startswith("error"):
                    duration = int(now - start)
                    logger.info(
                        "Task %s running for %ds (%s)", job_id, duration, status
                    )


task_manager = TaskManager()

__all__ = ["TaskManager", "task_manager"]
