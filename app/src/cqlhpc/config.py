from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

_CONFIG: Dict[str, str] = {}
_CONFIG_CTX: ContextVar[Optional[Dict[str, str]]] = ContextVar("cqlhpc_config_ctx", default=None)


def set_config(values: Dict[str, Any]) -> None:
    """Set CQLHPC runtime config (in-memory, per process)."""
    for key, val in values.items():
        _CONFIG[str(key)] = str(val)


def clear_config() -> None:
    _CONFIG.clear()


def _get_raw(key: str, default: Optional[str] = None) -> Optional[str]:
    ctx = _CONFIG_CTX.get()
    if ctx and key in ctx:
        return ctx[key]
    if key in _CONFIG:
        return _CONFIG[key]
    return os.environ.get(key, default)


def get_str(key: str, default: Optional[str] = None) -> str:
    val = _get_raw(key, default)
    return "" if val is None else str(val)


def get_int(key: str, default: int) -> int:
    try:
        return int(get_str(key, str(default)))
    except Exception:
        return default


def get_float(key: str, default: float) -> float:
    try:
        return float(get_str(key, str(default)))
    except Exception:
        return default


def get_bool(key: str, default: bool) -> bool:
    raw = get_str(key, "1" if default else "0").strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


@contextmanager
def use_config(values: Dict[str, Any] | None):
    """Temporarily apply config values for the current context."""
    if not values:
        yield
        return
    ctx_values = {str(k): str(v) for k, v in values.items()}
    token = _CONFIG_CTX.set(ctx_values)
    try:
        yield
    finally:
        _CONFIG_CTX.reset(token)
