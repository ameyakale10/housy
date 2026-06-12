"""Firestore backend integration tests — run against the isolated 'housy-test' database.

Skipped automatically if the firestore library or cloud credentials aren't available
(so the normal `pytest` run stays offline + green). Each test uses a unique household id
and cleans up after itself.
"""
import time
import uuid

import pytest

fb = pytest.importorskip("app.storage.firestore_backend")
from app import config  # noqa: E402

pytestmark = pytest.mark.firestore  # opt-in: run with `pytest -m firestore`


@pytest.fixture
def fs(monkeypatch):
    monkeypatch.setattr(config, "GCP_FIRESTORE_DATABASE", "housy-test")
    monkeypatch.setattr(config, "GCP_PROJECT", "housy-499021")
    fb._client = None  # rebuild the client against the test database
    try:
        fb._db().collection("meta").document("_ping").get()  # connectivity check
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Firestore unavailable: {e}")
    yield fb
    fb._client = None


def _cleanup_household(hid):
    hh = fb._hh(hid)
    for sub in ("meal_plans", "grocery_lists", "bills", "messages"):
        for d in hh.collection(sub).stream():
            d.reference.delete()
    hh.delete()


def test_profile_round_trip(fs):
    hid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        assert fs.read_profile(hid) is None
        fs.write_profile(hid, {"household_id": hid, "status": "not-onboarded"})
        assert fs.read_profile(hid)["status"] == "not-onboarded"
    finally:
        _cleanup_household(hid)


def test_grocery_transactional_update(fs):
    hid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        fs.save_grocery_list(hid, {"list_id": "L1", "household_id": hid, "items": []})
        fs.set_current_list(hid, "L1")
        fs.update_grocery_list(hid, "L1", lambda l: {**l, "items": l["items"] + [{"name": "paneer"}]})
        items = fs.current_grocery_list(hid)["items"]
        assert any(i["name"] == "paneer" for i in items)
    finally:
        _cleanup_household(hid)


def test_state_and_plan(fs):
    hid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        fs.save_meal_plan(hid, {"plan_id": "P1", "household_id": hid, "created_at": "2026-01-01", "days": [{"date": "Mon"}]})
        fs.set_current_plan(hid, "P1")
        fs.set_current_list(hid, "L9")
        assert fs.current_plan_id(hid) == "P1"
        assert fs.current_list_id(hid) == "L9"        # nested state merge preserved both
        assert fs.latest_meal_plan(hid)["plan_id"] == "P1"
    finally:
        _cleanup_household(hid)


def test_history_order(fs):
    hid = f"test-{uuid.uuid4().hex[:8]}"
    try:
        for i in range(3):
            fs.append_turn(hid, {"speaker": "A", "text": f"m{i}"})
            time.sleep(0.05)
        time.sleep(0.5)  # let server timestamps settle
        turns = fs.read_history(hid, n=2)
        assert [t["text"] for t in turns] == ["m1", "m2"]   # last 2, oldest->newest
    finally:
        _cleanup_household(hid)


def test_claim_sid_dedup(fs):
    sid = f"SMtest{uuid.uuid4().hex[:10]}"
    try:
        assert fs.claim_sid(sid) is True
        assert fs.claim_sid(sid) is False
    finally:
        fs._db().collection("processed_sids").document(sid).delete()


def test_invite_consume_single_use(fs):
    code = f"HOUSY-{uuid.uuid4().hex[:6].upper()}"
    try:
        fs.put_invite(code, {"household_id": "hX", "by": "+1", "expires": 9_999_999_999}, 0)
        assert fs.consume_invite(code, 0)["household_id"] == "hX"
        assert fs.consume_invite(code, 0) is None        # single-use
    finally:
        fs._db().collection("invites").document(code).delete()


def test_phone_household_mapping(fs):
    phone = f"+test{uuid.uuid4().hex[:8]}"
    try:
        assert fs.get_household_for_phone(phone) is None
        hid = fs.get_or_create_household(phone)
        assert hid.startswith("h")
        assert fs.get_or_create_household(phone) == hid   # stable
        assert fs.get_household_for_phone(phone) == hid
    finally:
        fs._db().collection("phone_index").document(phone).delete()
