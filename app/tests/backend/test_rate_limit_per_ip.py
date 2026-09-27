"""C4 fix: anonymous rate limiting is bucketed per client IP.

Previously a single global ``anon`` bucket meant one abusive IP exhausted the
anonymous/login budget for everyone. Anonymous callers are now keyed as
``anon:<ip>`` (falling back to the global ``anon`` bucket when no client
address is available); authenticated user buckets are unchanged.
"""

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from candyconc.services.backend import app, auth, rate_limit

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


@pytest.fixture(autouse=True)
def _clean_rate_limit_state():
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_two_client_ips_get_independent_anon_budgets():
    rate_limit.set_limit("anon", 2)

    rate_limit.check(None, client_host="203.0.113.1")
    rate_limit.check(None, client_host="203.0.113.1")
    with pytest.raises(HTTPException) as exc:
        rate_limit.check(None, client_host="203.0.113.1")
    assert exc.value.status_code == 429

    # A different IP still has its own full anon budget.
    rate_limit.check(None, client_host="203.0.113.2")
    rate_limit.check(None, client_host="203.0.113.2")
    with pytest.raises(HTTPException):
        rate_limit.check(None, client_host="203.0.113.2")


def test_anon_without_client_host_uses_global_bucket():
    rate_limit.set_limit("anon", 1)
    rate_limit.check(None)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check(None)
    assert exc.value.status_code == 429


def test_bogus_token_falls_into_per_ip_anon_bucket(monkeypatch):
    monkeypatch.setattr(auth, "username_for_token", lambda _t: None)
    rate_limit.set_limit("anon", 1)
    rate_limit.check("bogus-token", client_host="198.51.100.7")
    with pytest.raises(HTTPException):
        rate_limit.check("bogus-token", client_host="198.51.100.7")
    # Other IPs unaffected by the bogus-token abuser.
    rate_limit.check("bogus-token", client_host="198.51.100.8")


def test_user_token_bucket_is_unchanged_and_ip_independent(monkeypatch):
    monkeypatch.setattr(auth, "username_for_token", lambda _t: "bob")
    rate_limit.set_limit("bob", 1)
    rate_limit.check("tok", client_host="203.0.113.1")
    # Same user from a different IP shares the SAME user bucket.
    with pytest.raises(HTTPException) as exc:
        rate_limit.check("tok", client_host="203.0.113.99")
    assert exc.value.status_code == 429


def test_expired_ip_buckets_are_pruned(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(rate_limit.time, "time", lambda: now)
    rate_limit.set_window(1.0)

    for idx in range(3):
        rate_limit.check(None, client_host=f"198.51.100.{idx}")

    assert len(rate_limit._USAGE) == 3
    rate_limit._prune_usage(now + 2.0)

    assert rate_limit._USAGE == {}


def test_middleware_records_anon_usage_per_client_host():
    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    # Starlette's TestClient connects as "testclient" — the middleware must
    # record anonymous usage under the per-IP key, not the global bucket.
    assert any(key.startswith("anon:") for key in rate_limit._USAGE)
    assert "anon" not in rate_limit._USAGE
