import asyncio
from typing import Any, AsyncGenerator, Dict

# Simple in-memory progress registry for FAISS build jobs

_JOBS: Dict[str, asyncio.Queue[dict[str, Any]]] = {}


def create(job_id: str) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _JOBS[job_id] = q
    return q


def get(job_id: str) -> asyncio.Queue[dict[str, Any]] | None:
    return _JOBS.get(job_id)


def remove(job_id: str) -> None:
    _JOBS.pop(job_id, None)


async def stream(job_id: str) -> AsyncGenerator[dict[str, Any], None]:
    q = get(job_id)
    if q is None:
        return
    try:
        while True:
            item = await q.get()
            yield item
            if item.get("progress", 0) >= 100:
                break
    finally:
        remove(job_id)

