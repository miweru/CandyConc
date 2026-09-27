from __future__ import annotations

from typing import Literal

from candyconc.candyconc_copilot.policy_engine import PolicyEngine


def moderate(
    text: str,
    user: str = "default",
    policy: PolicyEngine | None = None,
) -> Literal["ok", "block"]:
    """Return moderation decision for ``text`` using ``PolicyEngine``."""

    try:
        pol = policy or PolicyEngine()
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PolicyEngine unavailable") from exc

    if not pol.get(user, "moderation_enabled", True):
        return "ok"
    if getattr(pol, "moderate", None) is None:
        raise RuntimeError("PolicyEngine lacks moderation support")
    return "ok" if pol.moderate(text) else "block"
