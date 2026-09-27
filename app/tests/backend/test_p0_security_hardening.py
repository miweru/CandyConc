"""Regression tests for the CONFIRMED P0 backend security hardening.

Covers:
  1. Rate limiting is non-zero by default (no longer unlimited).
  2. Salted KDF password hashing with backward-compatible legacy verify.
  3. Token TTL expiry and explicit revoke/logout.
  4. Route policy gaps (subcorpora/corpora).
  5. Release security validation wiring.

No mocks for the security logic itself.
"""

from __future__ import annotations

import time
from hashlib import sha256

import pytest
from fastapi import HTTPException

from candyconc.config import set as set_config
from candyconc.services.backend import auth, rate_limit
from candyconc.services.backend import route_matrix


# --------------------------------------------------------------------------- #
# Fix 1: Rate limiting default
# --------------------------------------------------------------------------- #
class TestRateLimitDefault:
    def setup_method(self):
        rate_limit.reset()

    def teardown_method(self):
        rate_limit.reset()

    def test_default_limit_is_non_zero(self):
        # The vulnerability: default was 0 (unlimited). It must now be bounded.
        assert rate_limit._RATE_LIMITS["default"] > 0
        assert rate_limit._RATE_LIMITS["anon"] > 0

    def test_exceeding_default_limit_raises_429(self):
        rate_limit.set_limit("default", 3)
        rate_limit.set_window(60.0)
        # No token -> anon bucket; pin it small too.
        rate_limit.set_limit("anon", 3)
        for _ in range(3):
            rate_limit.check(None)
        with pytest.raises(HTTPException) as exc:
            rate_limit.check(None)
        assert exc.value.status_code == 429

    def test_unknown_token_falls_back_to_anon_bucket(self):
        rate_limit.set_limit("anon", 2)
        rate_limit.set_window(60.0)
        # A bogus bearer token resolves to no user -> anon throttle applies.
        for _ in range(2):
            rate_limit.check("definitely-not-a-real-token")
        with pytest.raises(HTTPException) as exc:
            rate_limit.check("definitely-not-a-real-token")
        assert exc.value.status_code == 429


# --------------------------------------------------------------------------- #
# Fix 2: Salted KDF + legacy verify + constant time
# --------------------------------------------------------------------------- #
class TestPasswordHashing:
    def test_new_hash_is_salted_scrypt_and_verifies(self):
        h = auth.hash_password("s3cret")
        assert h.startswith("scrypt$")
        # Two hashes of the same password must differ (random salt).
        assert auth.hash_password("s3cret") != h
        assert auth.verify_password("s3cret", h)
        assert not auth.verify_password("wrong", h)

    def test_legacy_sha256_hash_still_verifies(self):
        legacy = sha256(b"legacypw").hexdigest()
        assert auth.verify_password("legacypw", legacy)
        assert not auth.verify_password("nope", legacy)

    def test_authenticate_upgrades_legacy_hash_on_login(self):
        saved_users = dict(auth._USERS)
        saved_tokens = dict(auth._tokens)
        try:
            auth._USERS["legacy"] = auth.User(
                "legacy", sha256(b"pw").hexdigest(), "user"
            )
            token = auth.authenticate("legacy", "pw")
            assert token is not None
            # Hash upgraded in place to salted scrypt.
            assert auth._USERS["legacy"].password.startswith("scrypt$")
            assert auth.verify_password("pw", auth._USERS["legacy"].password)
        finally:
            auth._USERS.clear()
            auth._USERS.update(saved_users)
            auth._tokens.clear()
            auth._tokens.update(saved_tokens)

    def test_wrong_password_fails(self):
        saved_users = dict(auth._USERS)
        try:
            auth._USERS["u"] = auth.User("u", auth.hash_password("right"), "user")
            assert auth.authenticate("u", "wrong") is None
            assert auth.authenticate("u", "right") is not None
        finally:
            auth._USERS.clear()
            auth._USERS.update(saved_users)


# --------------------------------------------------------------------------- #
# Fix 3: Token TTL + revoke
# --------------------------------------------------------------------------- #
class TestTokenLifecycle:
    def setup_method(self):
        self._users = dict(auth._USERS)
        self._tokens = dict(auth._tokens)
        self._expiry = dict(auth._token_expiry)

    def teardown_method(self):
        auth._USERS.clear()
        auth._USERS.update(self._users)
        auth._tokens.clear()
        auth._tokens.update(self._tokens)
        auth._token_expiry.clear()
        auth._token_expiry.update(self._expiry)

    def test_revoke_token_invalidates_it(self):
        auth._USERS["u"] = auth.User("u", auth.hash_password("pw"), "user")
        token = auth.authenticate("u", "pw")
        assert auth.username_for_token(token) == "u"
        assert auth.revoke_token(token) is True
        assert auth.username_for_token(token) is None

    def test_expired_token_rejected_and_pruned(self):
        auth._USERS["u"] = auth.User("u", auth.hash_password("pw"), "user")
        token = auth.authenticate("u", "pw")
        # Force expiry into the past.
        auth._token_expiry[token] = time.time() - 1
        assert auth.username_for_token(token) is None
        # Pruned from the live store.
        assert token not in auth._tokens

    def test_issued_token_has_expiry_recorded(self):
        auth._USERS["u"] = auth.User("u", auth.hash_password("pw"), "user")
        token = auth.authenticate("u", "pw")
        assert token in auth._token_expiry
        assert auth._token_expiry[token] > time.time()


# --------------------------------------------------------------------------- #
# Fix 4a: Route policy classification completeness
# --------------------------------------------------------------------------- #
class TestRoutePolicyCompleteness:
    def test_subcorpora_and_corpora_are_classified_as_user(self):
        assert route_matrix.policy_for_path(
            "/api/v1/subcorpora"
        ).access == route_matrix.AccessLevel.USER
        assert route_matrix.policy_for_path(
            "/api/v1/corpora"
        ).access == route_matrix.AccessLevel.USER

    def test_logout_is_public(self):
        assert route_matrix.policy_for_path(
            "/api/v1/logout"
        ).access == route_matrix.AccessLevel.PUBLIC

    def test_every_registered_api_route_resolves_to_a_policy(self):
        """CI-style guard: no backend API route may be unclassified."""
        from candyconc.services.backend.server import app as srv_app

        unclassified: list[str] = []
        for route in srv_app.routes:
            path = getattr(route, "path", None)
            if not path:
                continue
            if not route_matrix.requires_policy_for_path(path):
                continue
            # Replace path params with a concrete segment for matching.
            concrete = path.replace("{", "").replace("}", "")
            if route_matrix.policy_for_path(concrete) is None:
                unclassified.append(path)
        assert not unclassified, f"Unclassified backend routes: {sorted(unclassified)}"


# --------------------------------------------------------------------------- #
# Fix 5: Release security validation
# --------------------------------------------------------------------------- #
class TestReleaseSecurityValidation:
    def setup_method(self):
        self._rbac = auth.RBAC_ENABLED
        self._users = dict(auth._USERS)
        self._admin_tok = auth.DEFAULT_ADMIN_TOKEN

    def teardown_method(self):
        auth.RBAC_ENABLED = self._rbac
        auth._USERS.clear()
        auth._USERS.update(self._users)
        auth.DEFAULT_ADMIN_TOKEN = self._admin_tok
        set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")

    def test_validate_release_security_raises_on_fail_open(self):
        set_config("CANDYCONC_SECURITY_MODE", "release")
        auth.RBAC_ENABLED = False
        with pytest.raises(RuntimeError) as exc:
            auth.validate_release_security()
        assert "Unsafe CandyConc release security configuration" in str(exc.value)

    def test_validate_release_security_passes_when_hardened(self):
        set_config("CANDYCONC_SECURITY_MODE", "release")
        auth.RBAC_ENABLED = True
        auth.DEFAULT_ADMIN_TOKEN = None
        auth._USERS.clear()
        auth.create_user("opsadmin", "pw", "admin")
        # Should not raise.
        auth.validate_release_security()

    def test_startup_invokes_release_validation(self):
        # Confirm startup wires the validation in (item 6).
        import inspect

        from candyconc.services.backend import startup

        src = inspect.getsource(startup.StartupManager.start)
        assert "validate_release_security" in src


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
