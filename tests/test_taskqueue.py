"""Cloud Tasks tests — OIDC verification (fail-closed) + enqueue payload shape.

verify_oidc is security-critical (it's the only thing standing between the public
/tasks/process worker and an attacker), but every webhook test monkeypatches it away.
These tests exercise it directly by stubbing the Google token verifier.
"""
import sys
import types

import app.config as config
from app import taskqueue


def _patch_verifier(monkeypatch, claims=None, raises=False):
    """Stub google.oauth2.id_token.verify_oauth2_token (imported lazily inside verify_oidc)."""
    mod = types.ModuleType("google.oauth2.id_token")

    def _verify(token, request, audience=None):
        if raises:
            raise ValueError("bad token")
        return claims

    mod.verify_oauth2_token = _verify
    monkeypatch.setitem(sys.modules, "google.oauth2.id_token", mod)
    # google.auth.transport.requests.Request() is constructed but harmless; leave it real.


def test_rejects_non_bearer(monkeypatch):
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "sa@project.iam.gserviceaccount.com")
    assert taskqueue.verify_oidc("") is False
    assert taskqueue.verify_oidc("Token abc") is False


def test_accepts_valid_token_from_our_sa(monkeypatch):
    sa = "sa@project.iam.gserviceaccount.com"
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", sa)
    _patch_verifier(monkeypatch, claims={"email": sa, "email_verified": True})
    assert taskqueue.verify_oidc("Bearer goodtoken") is True
    # also accept the string form some issuers use
    _patch_verifier(monkeypatch, claims={"email": sa, "email_verified": "true"})
    assert taskqueue.verify_oidc("Bearer goodtoken") is True


def test_rejects_wrong_service_account(monkeypatch):
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "sa@project.iam.gserviceaccount.com")
    _patch_verifier(monkeypatch, claims={"email": "attacker@evil.com", "email_verified": True})
    assert taskqueue.verify_oidc("Bearer goodtoken") is False


def test_rejects_unverified_email(monkeypatch):
    sa = "sa@project.iam.gserviceaccount.com"
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", sa)
    _patch_verifier(monkeypatch, claims={"email": sa})                    # email_verified absent
    assert taskqueue.verify_oidc("Bearer goodtoken") is False
    _patch_verifier(monkeypatch, claims={"email": sa, "email_verified": False})
    assert taskqueue.verify_oidc("Bearer goodtoken") is False


def test_fails_closed_when_sa_unset(monkeypatch):
    """A misconfig (no expected SA) must REJECT, not accept any Google-signed token."""
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "")
    _patch_verifier(monkeypatch, claims={"email": "anyone@google.com", "email_verified": True})
    assert taskqueue.verify_oidc("Bearer goodtoken") is False


def test_rejects_when_verifier_raises(monkeypatch):
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "sa@project.iam.gserviceaccount.com")
    _patch_verifier(monkeypatch, raises=True)
    assert taskqueue.verify_oidc("Bearer tampered") is False


def test_missing_prod_secrets_flags_incomplete_cloud_tasks(monkeypatch):
    monkeypatch.setattr(config, "USE_CLOUD_TASKS", True)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "x")
    monkeypatch.setattr(config, "NUDGE_TOKEN", "a-strong-token")
    monkeypatch.setattr(config, "TASKS_WORKER_URL", "")
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "")
    assert any("TASKS_WORKER_URL" in m for m in config.missing_prod_secrets())
    # fully configured -> no Cloud Tasks complaint
    monkeypatch.setattr(config, "TASKS_WORKER_URL", "https://run/tasks/process")
    monkeypatch.setattr(config, "TASKS_SERVICE_ACCOUNT", "sa@project.iam.gserviceaccount.com")
    assert not any("TASKS_WORKER_URL" in m for m in config.missing_prod_secrets())
