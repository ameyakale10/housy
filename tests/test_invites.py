"""Invite-code tests — membership-gated creation, single-use + expiry redeem, linking."""
import time

import app.identity as identity
import app.invites as invites
import app.store as store
import app.tools as tools


def _household(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    identity.set_member_name(h, "+111", "Ameya")
    return h


def test_create_requires_membership(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    assert invites.create_invite(h, "+111") is not None      # a member can invite
    assert invites.create_invite(h, "+999") is None          # a non-member cannot


def test_extract_code():
    assert invites.extract_code("join HOUSY-4821 please") == "HOUSY-4821"
    assert invites.extract_code("HOUSY4821") == "HOUSY-4821"
    assert invites.extract_code("no code here") is None


def test_redeem_links_and_is_single_use(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    hid, inviter = invites.redeem(code, "+222")
    assert hid == h and inviter == "Ameya"
    assert identity.resolve_or_create_household("+222") == h   # now shares the household
    assert invites.redeem(code, "+333") is None                # burned (single-use)


def test_redeem_expired(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    monkeypatch.setattr(invites, "_now", lambda: time.time() + invites.TTL_SECONDS + 1000)
    assert invites.redeem(code, "+222") is None


def test_maybe_redeem(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    assert invites.maybe_redeem(f"join {code}", "+222")[0] == h
    assert invites.maybe_redeem("hello there", "+222") is None


def test_invite_tool_dispatch(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    r = tools.build_dispatch(h, "+111", [])["create_household_invite"]()
    assert r["ok"] and r["code"].startswith("HOUSY-")
