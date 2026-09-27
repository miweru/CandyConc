from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import json
import time
from pathlib import Path
import re

from candyconc.project import Project

try:  # optional dependency for metrics
    from candyconc.services.backend import metrics
except Exception:  # pragma: no cover - metrics not available
    metrics = None

logger = logging.getLogger(__name__)

#: Copilot tools that are not safe for ungated release auto-execution.  When
#: NO ACL is configured AND release security mode is active, tools listed here
#: are denied by default instead of running ungated.  Currently empty: the
#: cluster family was removed — its read tools run in release, and the
#: mutating cluster tools (cluster_save, cluster_export_md, semantic_recluster,
#: refine_cluster_label, ...) are registered ``read_only=False`` and therefore
#: route through the orchestrator's write-tool approval gate
#: (``orchestrator._should_require_approval`` via ``_is_tool_known_write``)
#: rather than being hard-denied here.
DEFAULT_DENY_TOOLS: frozenset[str] = frozenset()


class PolicyEngine:
    """Simple policy engine enforcing token budget and ACL.

    ``release_mode``: optional override for the security mode used by the
    no-ACL default-deny gate.  ``None`` (default) resolves
    ``CANDYCONC_SECURITY_MODE`` from :mod:`candyconc.config` lazily — the
    same source ``candyconc.services.backend.auth`` uses.
    """

    def __init__(
        self,
        token_budget: int = 1000,
        acl: Optional[Dict[str, List[str]]] = None,
        *,
        project: Project | None = None,
        release_mode: bool | None = None,
    ) -> None:
        self.token_budget = token_budget
        self.remaining = token_budget
        self.tokens_used = 0
        self.token_calls = 0
        self.acl = acl
        self.project = project
        self.release_mode = release_mode
        self._policy_cache: Dict[str, Any] = {}
        self._cache_time = 0.0

        self._block_patterns = [
            re.compile(r"</?sys>", re.I),
            re.compile(r"<<"),
            re.compile(r"ignore\s+all", re.I),
        ]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        """Load overrides from the associated project if available."""
        if not self.project:
            return
        budget = self.project.get_setting("token_budget")
        if budget is not None:
            try:
                new_budget = int(budget)
            except Exception:
                new_budget = self.token_budget
            if new_budget != self.token_budget:
                delta = new_budget - self.token_budget
                self.token_budget = new_budget
                self.remaining = max(0, min(self.remaining + delta, new_budget))
        acl_str = self.project.get_setting("tool_acl")
        if acl_str is not None:
            try:
                if acl_str.strip().startswith("{"):
                    acl_data = json.loads(acl_str)
                else:
                    allowed = [t.strip() for t in acl_str.split(",") if t.strip()]
                    acl_data = {"user": allowed}
                if isinstance(acl_data, dict):
                    self.acl = {str(k): list(v) for k, v in acl_data.items()}
            except Exception:
                logger.exception("Invalid ACL settings in project")
                raise

    def _is_release_mode(self) -> bool:
        """Whether fail-closed release security semantics are active."""
        if self.release_mode is not None:
            return bool(self.release_mode)
        try:
            from candyconc.config import get as get_config

            raw = get_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe") or ""
        except Exception:  # pragma: no cover - config unavailable (stubs)
            return False
        normalized = raw.strip().lower().replace("-", "_")
        return normalized in {"release", "production", "prod"}

    def check(self, role: str, tool: str, tokens: int) -> Dict[str, str]:
        """Return status for executing ``tool`` by ``role`` consuming ``tokens``."""
        self._refresh()
        if self.acl:
            allowed = self.acl.get(role, [])
            if tool not in allowed:
                return {"status": "error", "message": "Permission denied"}
        elif tool in DEFAULT_DENY_TOOLS and self._is_release_mode():
            # C2: an unset/empty ACL must not disable gating in release —
            # write/destructive tools are default-denied; read tools and the
            # dev mode keep the legacy allow-all behaviour.
            return {
                "status": "error",
                "message": (
                    "Permission denied: non-read-only tool blocked by release "
                    "default-deny (no tool ACL configured)"
                ),
            }
        if self.remaining < tokens:
            return {"status": "error", "message": "Token budget exhausted"}
        self.remaining -= tokens
        self.tokens_used += tokens
        self.token_calls += 1
        if metrics is not None:
            metrics.inc_tokens(tokens)
        return {"status": "ok"}

    def reset(self) -> None:
        """Reset token usage."""
        self._refresh()
        self.remaining = self.token_budget
        self.tokens_used = 0
        self.token_calls = 0

    # ------------------------------------------------------------------
    # policy getters
    # ------------------------------------------------------------------
    def _load_policy(self) -> None:
        if time.time() - self._cache_time < 30:
            return
        self._cache_time = time.time()

        from candyconc.config import get as get_config

        user_file_val = get_config(
            "CANDYCONC_USER_FILE",
            str(Path(__file__).resolve().parents[1] / "config" / "users.json"),
        )
        user_file = Path(user_file_val or "") if user_file_val is not None else Path("")
        try:
            entries = json.loads(user_file.read_text(encoding="utf-8"))
        except Exception:
            entries = []
        users = {e.get("username"): e for e in entries if e.get("username")}

        self._policy_cache = {"users": users}

    def get(self, user: str, key: str, default: Any | None = None) -> Any:
        self._load_policy()
        user_spec = self._policy_cache.get("users", {}).get(user, {})
        if key in user_spec:
            return user_spec[key]
        return default

    # ------------------------------------------------------------------
    # moderation helpers
    # ------------------------------------------------------------------
    def moderate(self, text: str) -> bool:
        """Return ``True`` if ``text`` passes moderation."""

        for pat in self._block_patterns:
            if pat.search(text):
                return False
        return True
