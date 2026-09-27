from __future__ import annotations

import json
import stat

import pytest

from candyconc.services.backend.auth import verify_password
from candyconc.tools.user_bootstrap import write_bootstrap_user_file


def test_bootstrap_user_file_hashes_password_and_locks_permissions(tmp_path):
    target = write_bootstrap_user_file(
        tmp_path / "users.json",
        username="release-admin",
        password="correct horse battery staple",
    )

    entries = json.loads(target.read_text(encoding="utf-8"))
    assert entries[0]["username"] == "release-admin"
    assert entries[0]["role"] == "admin"
    assert entries[0]["password"] != "correct horse battery staple"
    assert verify_password("correct horse battery staple", entries[0]["password"])
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_bootstrap_rejects_packaged_sample_usernames(tmp_path):
    with pytest.raises(ValueError, match="sample username"):
        write_bootstrap_user_file(
            tmp_path / "users.json",
            username="alice",
            password="correct horse battery staple",
        )


def test_bootstrap_refuses_overwrite_without_force(tmp_path):
    target = tmp_path / "users.json"
    write_bootstrap_user_file(
        target,
        username="release-admin",
        password="correct horse battery staple",
    )

    with pytest.raises(FileExistsError):
        write_bootstrap_user_file(
            target,
            username="release-admin-2",
            password="correct horse battery staple",
        )

    write_bootstrap_user_file(
        target,
        username="release-admin-2",
        password="correct horse battery staple",
        force=True,
    )
    entries = json.loads(target.read_text(encoding="utf-8"))
    assert entries[0]["username"] == "release-admin-2"
