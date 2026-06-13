"""Invite tests — membership gate, high-entropy codes, single-use/expiry, rate limiting,
and not silently moving an existing onboarded member."""
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
    assert invites.create_invite(h, "+111") is not None       # a member can invite
    assert invites.create_invite(h, "+999") is None           # a non-member cannot


def test_code_is_six_char_unambiguous(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    body = code.split("-")[1]
    assert len(body) == 6
    assert all(c in invites._ALPHABET for c in body)          # no ambiguous 0/O/1/I


def test_extract_code(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    assert invites.extract_code(f"join {code} please") == code
    assert invites.extract_code(code.replace("-", "")) == code
    assert invites.extract_code("no code here") is None


def test_redeem_links_and_single_use(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    res = invites.redeem(code, "+222")
    assert res["ok"] and res["household_id"] == h and res["inviter"] == "Ameya"
    assert identity.resolve_or_create_household("+222") == h  # now shares the household
    assert invites.redeem(code, "+333")["ok"] is False        # burned (single-use)


def test_redeem_expired(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    monkeypatch.setattr(invites, "_now", lambda: time.time() + invites.TTL_SECONDS + 1000)
    assert invites.redeem(code, "+222")["reason"] == "invalid"


def test_redeem_rate_limited(tmp_path, monkeypatch):
    _household(tmp_path, monkeypatch)
    for _ in range(invites._MAX_ATTEMPTS):
        invites.redeem("HOUSY-ZZZZZZ", "+222")               # burn the attempt budget
    assert invites.redeem("HOUSY-ZZZZZZ", "+222")["reason"] == "rate_limited"


def test_onboarded_member_not_silently_moved(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    other = identity.resolve_or_create_household("+222")      # +222 in their own household
    store.write_profile(other, {**(store.read_profile(other) or {}), "status": "onboarded"})
    code = invites.create_invite(h, "+111")
    assert invites.redeem(code, "+222")["reason"] == "already_member"


def test_redeem_carries_name_and_cleans_orphan(tmp_path, monkeypatch):
    """Partner texts first (gets their own household + tells Housy their name), THEN joins.
    Their name must carry over, and their old solo household must be cleaned up."""
    h = _household(tmp_path, monkeypatch)
    other = identity.resolve_or_create_household("+222")      # +222's own solo household
    identity.set_member_name(other, "+222", "Swati")          # she told Housy her name first
    assert other != h

    code = invites.create_invite(h, "+111")
    res = invites.redeem(code, "+222")
    assert res["ok"] and res["household_id"] == h

    assert identity.member_name(h, "+222") == "Swati"         # name carried into the couple
    assert store.read_profile(other) is None                  # orphan household removed
    # she is NOT left as a phantom empty-name member anywhere
    members = store.read_profile(h)["members"]
    assert any(m["phone"] == "+222" and m["name"] == "Swati" for m in members)


def test_maybe_redeem(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    code = invites.create_invite(h, "+111")
    assert invites.maybe_redeem(f"join {code}", "+222")["household_id"] == h
    assert invites.maybe_redeem("hello there", "+222") is None


def test_invite_tool_dispatch(tmp_path, monkeypatch):
    h = _household(tmp_path, monkeypatch)
    r = tools.build_dispatch(h, "+111", [])["create_household_invite"]()
    assert r["ok"] and r["code"].startswith("HOUSY-") and r["expires_days"] == invites.TTL_DAYS
