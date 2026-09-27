from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hashlib
import hmac
import logging
from pathlib import Path
import base64
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Header, Request
from starlette.requests import HTTPConnection
import contextlib

from candyconc.config import get as get_config

logger = logging.getLogger(__name__)

RBAC_ENABLED = get_config("CANDYCONC_ENABLE_RBAC", "0") == "1"

SECURITY_MODE_RELEASE = "release"
SECURITY_MODE_LOCAL_DEV_UNSAFE = "local_dev_unsafe"
_DEFAULT_USERNAMES = {"alice", "bob"}
LOCAL_DEV_USERNAME = "local-dev"
LOCAL_DEV_ROLE = "admin"

# Single normalization point for every release-vs-dev decision in the backend.
# Mirrors the alias table in candyconc.config._normalize_security_mode so that
# values injected at runtime (config.set bypasses pydantic validation) behave
# exactly like values validated at startup: ``production``/``prod`` MUST
# activate the same fail-closed hardening as ``release``. Unknown values map to
# neither mode (not release, but also no unsafe token transport).
_SECURITY_MODE_ALIASES = {
    "release": SECURITY_MODE_RELEASE,
    "production": SECURITY_MODE_RELEASE,
    "prod": SECURITY_MODE_RELEASE,
    "local_dev_unsafe": SECURITY_MODE_LOCAL_DEV_UNSAFE,
    "local_dev": SECURITY_MODE_LOCAL_DEV_UNSAFE,
    "local": SECURITY_MODE_LOCAL_DEV_UNSAFE,
    "dev": SECURITY_MODE_LOCAL_DEV_UNSAFE,
    "unsafe": SECURITY_MODE_LOCAL_DEV_UNSAFE,
}


def security_mode() -> str:
    """Return the normalized backend security mode."""
    raw = (get_config("CANDYCONC_SECURITY_MODE", SECURITY_MODE_LOCAL_DEV_UNSAFE) or "").strip()
    canonical = raw.lower().replace("-", "_") or SECURITY_MODE_LOCAL_DEV_UNSAFE
    return _SECURITY_MODE_ALIASES.get(canonical, canonical)


def is_release_mode() -> bool:
    """Return whether fail-closed release security semantics are active."""
    return security_mode() == SECURITY_MODE_RELEASE


def is_local_dev_unsafe_mode() -> bool:
    """Return whether explicitly unsafe local-development semantics are active."""
    return security_mode() == SECURITY_MODE_LOCAL_DEV_UNSAFE


def allow_unsafe_token_transport() -> bool:
    """Allow query/body tokens only in the explicit local-dev mode."""
    return is_local_dev_unsafe_mode()


# --- Password hashing (salted KDF, backward compatible with legacy SHA-256) ---
#
# argon2 / bcrypt are not vendored, so we use the stdlib scrypt KDF with a
# per-password random salt and constant-time verification. Legacy unsalted
# SHA-256 digests (64 hex chars) are still recognised and verified so existing
# user files keep working, and they are transparently upgraded on next login.

_SCRYPT_PREFIX = "scrypt$"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16


def _is_scrypt_hash(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith(_SCRYPT_PREFIX)


def _is_legacy_sha256(stored: str) -> bool:
    if not isinstance(stored, str) or len(stored) != 64:
        return False
    try:
        int(stored, 16)
    except ValueError:
        return False
    return True


def hash_password(password: str) -> str:
    """Return a salted scrypt hash string for ``password``."""
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(derived).decode("ascii")
    return f"{_SCRYPT_PREFIX}{_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${hash_b64}"


def _normalize_password(password: str) -> str:
    """Return a stored representation, hashing plaintext but passing through
    already-hashed (scrypt or legacy SHA-256) values unchanged."""
    if _is_scrypt_hash(password) or _is_legacy_sha256(password):
        return password
    return hash_password(password)


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification supporting scrypt and legacy SHA-256."""
    if not isinstance(stored, str) or not stored:
        return False
    if _is_scrypt_hash(stored):
        try:
            _, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
            n, r, p = int(n_s), int(r_s), int(p_s)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            derived = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                dklen=len(expected),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(derived, expected)
    if _is_legacy_sha256(stored):
        candidate = sha256(password.encode()).hexdigest()
        return hmac.compare_digest(candidate, stored)
    return False


@dataclass
class User:
    username: str
    password: str
    role: str



_DEFAULT_FILE = Path(__file__).resolve().parents[4] / "config" / "users.json"


def _load_users(file_path: Path) -> Dict[str, User]:
    if not file_path.is_file():
        return {}
    try:
        entries = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    users: Dict[str, User] = {}
    for entry in entries:
        username = entry.get("username")
        password = entry.get("password")
        role = entry.get("role", "user")
        if username and password:
            users[username] = User(
                username,
                _normalize_password(password),
                role,
            )
    return users


_USERS: Dict[str, User] = {}

user_file = Path(get_config("CANDYCONC_USER_FILE", str(_DEFAULT_FILE))).expanduser()
if not user_file.is_absolute():
    user_file = (Path(__file__).resolve().parents[4] / user_file).resolve()
    if not user_file.is_file():
        # Installed package: no source checkout above it, the users file lives
        # with the user data (python -m candyconc.tools.user_bootstrap writes it).
        from candyconc.paths import data_dir

        user_file = data_dir() / "users.json"
_USERS.update(_load_users(user_file))

_tokens: Dict[str, str] = {}
# Absolute UNIX expiry timestamp per issued token. Tokens absent from this map
# (e.g. test-injected or the implicit dev admin token) never expire, preserving
# backward compatibility. Revoked tokens are removed from ``_tokens``.
_token_expiry: Dict[str, float] = {}


def _token_ttl_seconds() -> int:
    """Token lifetime in seconds (0 disables expiry). Configurable via env."""
    raw = os.environ.get("CANDYCONC_TOKEN_TTL_SECONDS")
    if raw is None or not str(raw).strip():
        return 12 * 60 * 60  # 12h default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 12 * 60 * 60
    return value if value >= 0 else 12 * 60 * 60


def _issue_token(username: str) -> str:
    """Mint a new bearer token for ``username`` with a TTL."""
    token = secrets.token_hex(16)
    _tokens[token] = username
    ttl = _token_ttl_seconds()
    if ttl > 0:
        _token_expiry[token] = time.time() + ttl
    return token


def _token_is_expired(token: str) -> bool:
    expiry = _token_expiry.get(token)
    return expiry is not None and time.time() >= expiry


def _resolve_token(token: Optional[str]) -> Optional[str]:
    """Return the username for a live token, pruning it if expired."""
    if not token:
        return None
    if _token_is_expired(token):
        revoke_token(token)
        return None
    return _tokens.get(token)


def revoke_token(token: Optional[str]) -> bool:
    """Revoke ``token`` (logout). Returns True if a token was removed."""
    if not token:
        return False
    removed = _tokens.pop(token, None) is not None
    _token_expiry.pop(token, None)
    return removed


ROLES = ["user", "annotator", "manager", "admin"]
_ROLE_LEVELS = {role: i for i, role in enumerate(ROLES)}

# RBAC can be disabled for single-user setups
DEFAULT_ADMIN_TOKEN: str | None = None

if not RBAC_ENABLED:
    if is_local_dev_unsafe_mode():
        DEFAULT_ADMIN_TOKEN = secrets.token_hex(16)
        admin_user = next((u.username for u in _USERS.values() if u.role == "admin"), None)
        if admin_user:
            _tokens[DEFAULT_ADMIN_TOKEN] = admin_user


def using_default_user_file() -> bool:
    """Return whether the packaged sample user file is active."""
    try:
        return user_file.resolve() == _DEFAULT_FILE.resolve()
    except Exception:
        return False


def release_security_issues() -> list[str]:
    """Return fail-closed release security configuration problems."""
    if not is_release_mode():
        return []
    issues: list[str] = []
    if not RBAC_ENABLED:
        issues.append("CANDYCONC_ENABLE_RBAC must be true in release mode")
    if using_default_user_file() and any(name in _USERS for name in _DEFAULT_USERNAMES):
        issues.append("packaged sample users must not be used in release mode")
    if not have_users():
        issues.append("at least one explicit user must be configured in release mode")
    if DEFAULT_ADMIN_TOKEN is not None:
        issues.append("implicit default admin token is not allowed in release mode")
    return issues


def validate_release_security() -> None:
    """Raise when release mode is configured in a fail-open way."""
    issues = release_security_issues()
    if issues:
        joined = "; ".join(issues)
        raise RuntimeError(f"Unsafe CandyConc release security configuration: {joined}")


def list_users() -> Dict[str, str]:
    """Return a mapping of usernames to roles."""
    return {u.username: u.role for u in _USERS.values()}


def have_users() -> bool:
    """Return ``True`` when at least one user is configured."""
    return bool(_USERS)


def set_role(username: str, role: str) -> None:
    """Update ``username`` to the given ``role``."""
    if username in _USERS:
        _USERS[username].role = role


def create_user(username: str, password: str, role: str = "user") -> None:
    """Add a new user with ``role``."""
    _USERS[username] = User(username, _normalize_password(password), role)


def authenticate(username: str, password: str) -> Optional[str]:
    user = _USERS.get(username)
    if user and verify_password(password, user.password):
        # Transparently upgrade legacy unsalted SHA-256 hashes to salted scrypt.
        if _is_legacy_sha256(user.password):
            user.password = hash_password(password)
        token = _issue_token(username)
        return token
    return None


def _is_local_dev_principal(username: Optional[str]) -> bool:
    return (
        username == LOCAL_DEV_USERNAME
        and not RBAC_ENABLED
        and is_local_dev_unsafe_mode()
    )


def _current_user(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    username = _resolve_token(token)
    if not username:
        return None
    if _is_local_dev_principal(username):
        return User(username, "", LOCAL_DEV_ROLE)
    return _USERS.get(username)


def get_token(authorization: str | None = Header(default=None)) -> Optional[str]:
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None


async def get_user_token(
    connection: HTTPConnection,
    authorization: str | None = Header(default=None),
    token: str | None = None,
) -> Optional[str]:
    """Return auth token.

    Release mode accepts only header tokens. Query/body token transport is kept
    for the explicitly unsafe local-dev mode so existing local workflows can be
    migrated without silently weakening release deployments.
    """
    header_token = get_token(authorization)
    if header_token is None:
        header_token = get_token(connection.headers.get("authorization"))
    if header_token:
        return header_token
    if is_release_mode():
        return None
    query_token = token
    if query_token is None:
        with contextlib.suppress(Exception):
            query_token = connection.query_params.get("token")  # type: ignore[attr-defined]
    if query_token and allow_unsafe_token_transport():
        return query_token
    if (
        isinstance(connection, Request)
        and connection.headers.get("content-type", "").startswith("application/json")
        and allow_unsafe_token_transport()
    ):
        with contextlib.suppress(Exception):
            body = await connection.json()
            if isinstance(body, dict):
                return body.get("token")
    return None


def username_for_token(token: Optional[str]) -> Optional[str]:
    """Return the username associated with ``token``."""
    if not token:
        return "guest" if (not RBAC_ENABLED and is_local_dev_unsafe_mode()) else None
    return _resolve_token(token)


def current_username(token: Optional[str] = Depends(get_user_token)) -> Optional[str]:
    """Return username derived from request token."""
    return username_for_token(token)


def role_for_token(token: Optional[str]) -> Optional[str]:
    """Return the role associated with ``token`` if valid."""
    user = _current_user(token)
    return user.role if user else None


def _enforce_role(required: str, user: Optional[User]) -> None:
    """Shared RBAC check for token- and username-resolved principals."""
    if not RBAC_ENABLED:
        if not is_local_dev_unsafe_mode():
            raise HTTPException(
                status_code=503,
                detail="RBAC must be enabled unless CANDYCONC_SECURITY_MODE=local_dev_unsafe",
            )
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_level = _ROLE_LEVELS.get(user.role, 0)
    req_level = _ROLE_LEVELS.get(required, 0)
    if user_level < req_level:
        raise HTTPException(status_code=403, detail="Forbidden")
    if required == "manager" and user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Forbidden")


def require_role(required: str):
    def dependency(token: Optional[str] = Depends(get_user_token)) -> None:
        if not RBAC_ENABLED:
            _enforce_role(required, None)
            return
        _enforce_role(required, _current_user(token))

    return dependency


def require_role_for_username(required: str, username: Optional[str]) -> None:
    """RBAC check for a username resolved out-of-band (WS-ticket auth path)."""
    if not RBAC_ENABLED:
        _enforce_role(required, None)
        return
    user = _USERS.get(username) if username else None
    _enforce_role(required, user)


# --- One-time WebSocket tickets (A7) ----------------------------------------
#
# Browsers cannot set an Authorization header on ``new WebSocket()``, and
# release mode (correctly) refuses query/body token transport. WS consumers
# therefore mint a short-TTL one-time ticket over authenticated REST
# (POST /api/v1/ws-ticket) and pass it as ``?ticket=`` on the WS handshake.
# Tickets are single-use (popped on redeem), expire after a few seconds, and
# only carry the username — role checks happen at redeem time against the
# current user table.

_WS_TICKETS: Dict[str, Tuple[str, float]] = {}
_WS_TICKETS_LOCK = threading.Lock()
_WS_TICKET_MAX_OUTSTANDING = 1024


def ws_ticket_ttl_seconds() -> float:
    raw = os.environ.get("CANDYCONC_WS_TICKET_TTL_SECONDS") or get_config(
        "CANDYCONC_WS_TICKET_TTL_SECONDS", "30"
    )
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 30.0
    return value if value > 0 else 30.0


def _prune_ws_tickets_locked(now: float) -> None:
    expired = [t for t, (_, exp) in _WS_TICKETS.items() if now >= exp]
    for t in expired:
        _WS_TICKETS.pop(t, None)
    # Hard cap so a misbehaving client cannot grow the map unboundedly;
    # evict the soonest-to-expire tickets first.
    while len(_WS_TICKETS) >= _WS_TICKET_MAX_OUTSTANDING:
        oldest = min(_WS_TICKETS, key=lambda t: _WS_TICKETS[t][1])
        _WS_TICKETS.pop(oldest, None)


def mint_ws_ticket(username: str) -> Tuple[str, float]:
    """Mint a one-time WS ticket for ``username``; returns (ticket, ttl)."""
    ttl = ws_ticket_ttl_seconds()
    now = time.time()
    ticket = secrets.token_urlsafe(24)
    with _WS_TICKETS_LOCK:
        _prune_ws_tickets_locked(now)
        _WS_TICKETS[ticket] = (str(username), now + ttl)
    return ticket, ttl


def redeem_ws_ticket(ticket: Optional[str]) -> Optional[str]:
    """One-time redeem: return the username for a live ticket, else None."""
    if not ticket:
        return None
    with _WS_TICKETS_LOCK:
        entry = _WS_TICKETS.pop(ticket, None)
    if entry is None:
        return None
    username, expiry = entry
    if time.time() >= expiry:
        return None
    return username


# --- Audit log lite (B10c) ---------------------------------------------------
#
# Structured JSONL append for security-relevant events: auth (login, failed
# login, logout, WS-ticket mint). Best-effort: auditing must never break the
# request path.
# Size-bounded via a single rotation (audit.jsonl -> audit.jsonl.1) once the
# active file exceeds CANDYCONC_AUDIT_LOG_MAX_BYTES.

_AUDIT_LOCK = threading.Lock()
_AUDIT_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_AUDIT_DISABLED_VALUES = {"0", "off", "false", "disabled", "none"}


def audit_log_path() -> Optional[Path]:
    """Resolved audit log path, or None when auditing is disabled."""
    raw = os.environ.get("CANDYCONC_AUDIT_LOG_PATH") or get_config(
        "CANDYCONC_AUDIT_LOG_PATH", ""
    )
    raw = str(raw or "").strip()
    if raw.lower() in _AUDIT_DISABLED_VALUES:
        return None
    if raw:
        return Path(raw).expanduser()
    from candyconc.paths import logs_dir

    return logs_dir() / "audit.jsonl"


def _audit_max_bytes() -> int:
    raw = os.environ.get("CANDYCONC_AUDIT_LOG_MAX_BYTES") or get_config(
        "CANDYCONC_AUDIT_LOG_MAX_BYTES", str(_AUDIT_DEFAULT_MAX_BYTES)
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return _AUDIT_DEFAULT_MAX_BYTES
    return value if value > 0 else _AUDIT_DEFAULT_MAX_BYTES


def audit_event(event: str, actor: Optional[str] = None, **details: Any) -> None:
    """Append a structured audit record. Best-effort, never raises."""
    try:
        path = audit_log_path()
        if path is None:
            return
        record: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": str(event),
            "actor": actor,
        }
        for key, value in details.items():
            if key not in record:
                record[key] = value
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _AUDIT_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size >= _audit_max_bytes():
                path.replace(path.with_name(path.name + ".1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:  # pragma: no cover - auditing is strictly best-effort
        logger.warning("audit_event failed for %s", event, exc_info=True)


def add_user(username: str, password: str, role: str = "user") -> None:
    """Create a new user entry."""
    create_user(username, password, role)
