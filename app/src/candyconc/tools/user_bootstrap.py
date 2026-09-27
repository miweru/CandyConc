from __future__ import annotations

from candyconc.paths import data_dir
import argparse
import getpass
import json
import os
import shlex
import stat
import sys
from pathlib import Path
from typing import Sequence

from candyconc.services.backend.auth import ROLES, hash_password


_SAMPLE_USERNAMES = {"alice", "bob", "charlie"}
_DEFAULT_PASSWORD_ENV = "CANDYCONC_BOOTSTRAP_PASSWORD"


def _resolve_output(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def _validate_bootstrap_user(username: str, role: str, password: str) -> None:
    if not username or any(ch.isspace() for ch in username):
        raise ValueError("username must be non-empty and contain no whitespace")
    if username in _SAMPLE_USERNAMES:
        raise ValueError(f"sample username {username!r} is not allowed for release bootstrap")
    if role not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(ROLES)}")
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")


def write_bootstrap_user_file(
    output: str | os.PathLike[str],
    *,
    username: str,
    password: str,
    role: str = "admin",
    force: bool = False,
) -> Path:
    """Create a release user file with one scrypt-hashed bootstrap user."""

    _validate_bootstrap_user(username, role, password)
    target = _resolve_output(output)
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    payload = [
        {
            "username": username,
            "password": hash_password(password),
            "role": role,
        }
    ]
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(target)
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return target


def _password_from_env_or_prompt(env_name: str) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"set {env_name} or run interactively to enter the bootstrap password"
        )
    first = getpass.getpass("Bootstrap password: ")
    second = getpass.getpass("Repeat bootstrap password: ")
    if first != second:
        raise ValueError("passwords do not match")
    return first


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a release-safe CandyConc users.json file.",
    )
    parser.add_argument(
        "--output",
        default=str(data_dir() / "users.json"),
        help="Target users.json path. Default: users.json in the CandyConc data directory",
    )
    parser.add_argument("--username", required=True, help="Bootstrap username")
    parser.add_argument(
        "--role",
        default="admin",
        choices=ROLES,
        help="Bootstrap role. Default: admin",
    )
    parser.add_argument(
        "--password-env",
        default=_DEFAULT_PASSWORD_ENV,
        help=f"Environment variable containing the password. Default: {_DEFAULT_PASSWORD_ENV}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing target file.",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="Print export lines for CANDYCONC_USER_FILE/RBAC/release mode.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        password = _password_from_env_or_prompt(args.password_env)
        target = write_bootstrap_user_file(
            args.output,
            username=args.username,
            password=password,
            role=args.role,
            force=bool(args.force),
        )
    except Exception as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
    print(f"created {target}")
    if args.print_env:
        print(f"export CANDYCONC_USER_FILE={shlex.quote(str(target))}")
        print("export CANDYCONC_ENABLE_RBAC=1")
        print("export CANDYCONC_SECURITY_MODE=release")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
