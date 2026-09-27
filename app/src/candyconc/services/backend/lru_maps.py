"""Small LRU helpers for backend maps that keep object identity."""

from __future__ import annotations

from collections.abc import MutableMapping
from contextlib import suppress
from typing import Any, Callable, Iterable


def mark_lru_used(cache: MutableMapping[str, Any], key: str) -> None:
    move_to_end = getattr(cache, "move_to_end", None)
    if callable(move_to_end) and key in cache:
        move_to_end(key)


def close_quietly(value: Any) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def trim_lru_cache(
    cache: MutableMapping[str, Any],
    limit: int,
    *,
    protected_ids: Iterable[int] = (),
    on_evict: Callable[[str, Any], None] | None = None,
) -> None:
    protected = set(protected_ids)
    while len(cache) > max(1, int(limit)):
        evict_key = None
        for key, value in cache.items():
            if id(value) not in protected:
                evict_key = key
                break
        if evict_key is None:
            return
        evicted = cache.pop(evict_key)
        if on_evict is not None:
            on_evict(evict_key, evicted)
