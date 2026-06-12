"""Firestore implementation of the store API (selected when STORAGE_BACKEND=firestore).

Every function matches `store.py`'s signature, so the rest of the app is unchanged. The
cross-thread lock the file backend used is replaced here by Firestore **transactions**
(correct across many Cloud Run instances) and an atomic `create()` for SID dedup.

Data model:
  households/{hid}                       {profile{}, state{}, summary, store_prefs{}}
  households/{hid}/meal_plans/{plan_id}
  households/{hid}/grocery_lists/{list_id}
  households/{hid}/bills/{bill_id}
  households/{hid}/messages/{auto}       {**turn, _ts: server_timestamp}
  phone_index/{phone}                    {household_id}
  invites/{code}                         {household_id, by, expires}
  redeem_attempts/{phone}                {attempts: [..]}
  processed_sids/{sid}                   {_ts}
  meta/counters                          {households: int}
"""
import contextlib
from typing import Callable, List, Optional

from google.api_core import exceptions as gexc
from google.cloud import firestore

from app import config
from app.config import DEFAULT_HOUSEHOLD_ID

_client = None


def _db() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client(
            project=config.GCP_PROJECT or None,
            database=config.GCP_FIRESTORE_DATABASE,
        )
    return _client


def _hh(hid: str):
    return _db().collection("households").document(hid)


def _hh_dict(hid: str) -> Optional[dict]:
    snap = _hh(hid).get()
    return snap.to_dict() if snap.exists else None


# household_lock is a no-op here (transactions provide atomicity).
@contextlib.contextmanager
def household_lock(household_id: str):
    yield


# ── profile ───────────────────────────────────────────────────────────────
def read_profile(household_id: str = DEFAULT_HOUSEHOLD_ID) -> Optional[dict]:
    d = _hh_dict(household_id)
    return d.get("profile") if d else None


def write_profile(household_id: str, profile: dict) -> None:
    _hh(household_id).set({"profile": profile}, merge=True)


def update_profile(household_id: str, mutate: Callable[[dict], dict]) -> dict:
    """Atomic read-modify-write of the profile inside a Firestore transaction, so two
    partners saving at the same instant can't overwrite each other's fields. `mutate`
    must be pure — the transaction may run it more than once on contention."""
    ref = _hh(household_id)

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        current = (snap.to_dict() or {}).get("profile") if snap.exists else None
        updated = mutate(current or {"household_id": household_id})
        txn.set(ref, {"profile": updated}, merge=True)
        return updated

    return _txn(_db().transaction())


# ── meal plans / grocery lists / bills ────────────────────────────────────
def save_meal_plan(household_id: str, plan: dict) -> None:
    _hh(household_id).collection("meal_plans").document(plan["plan_id"]).set(plan)


def latest_meal_plan(household_id: str) -> Optional[dict]:
    pid = current_plan_id(household_id)
    if pid:
        snap = _hh(household_id).collection("meal_plans").document(pid).get()
        if snap.exists:
            return snap.to_dict()
    q = (_hh(household_id).collection("meal_plans")
         .order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).stream())
    for snap in q:
        return snap.to_dict()
    return None


def save_grocery_list(household_id: str, glist: dict) -> None:
    _hh(household_id).collection("grocery_lists").document(glist["list_id"]).set(glist)


def read_grocery_list(household_id: str, list_id: str) -> Optional[dict]:
    snap = _hh(household_id).collection("grocery_lists").document(list_id).get()
    return snap.to_dict() if snap.exists else None


def update_grocery_list(household_id: str, list_id: str, mutate: Callable[[dict], dict]) -> Optional[dict]:
    ref = _hh(household_id).collection("grocery_lists").document(list_id)

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return None
        updated = mutate(snap.to_dict())
        txn.set(ref, updated)
        return updated

    return _txn(_db().transaction())


def current_grocery_list(household_id: str) -> Optional[dict]:
    lid = current_list_id(household_id)
    return read_grocery_list(household_id, lid) if lid else None


def save_bill(household_id: str, bill: dict) -> None:
    _hh(household_id).collection("bills").document(bill["bill_id"]).set(bill)


# ── memory summary + history ──────────────────────────────────────────────
def read_memory_summary(household_id: str = DEFAULT_HOUSEHOLD_ID) -> str:
    d = _hh_dict(household_id)
    return (d.get("summary", "") if d else "") or ""


def write_memory_summary(household_id: str, text: str) -> None:
    _hh(household_id).set({"summary": text}, merge=True)


def append_turn(household_id: str, turn: dict) -> None:
    doc = dict(turn)
    doc["_ts"] = firestore.SERVER_TIMESTAMP   # reliable ordering, even if turn has no ts
    _hh(household_id).collection("messages").add(doc)


def read_history(household_id: str = DEFAULT_HOUSEHOLD_ID, n: int = 12) -> List[dict]:
    q = (_hh(household_id).collection("messages")
         .order_by("_ts", direction=firestore.Query.DESCENDING).limit(n).stream())
    turns = []
    for snap in q:
        d = snap.to_dict()
        d.pop("_ts", None)
        turns.append(d)
    turns.reverse()  # oldest -> newest
    return turns


# ── per-household state (current list / plan) ─────────────────────────────
def _state(hid: str) -> dict:
    d = _hh_dict(hid)
    return (d.get("state", {}) if d else {}) or {}


def set_current_list(household_id: str, list_id: str) -> None:
    _hh(household_id).set({"state": {"current_list_id": list_id}}, merge=True)


def current_list_id(household_id: str) -> Optional[str]:
    return _state(household_id).get("current_list_id")


def set_current_plan(household_id: str, plan_id: str) -> None:
    _hh(household_id).set({"state": {"current_plan_id": plan_id}}, merge=True)


def current_plan_id(household_id: str) -> Optional[str]:
    return _state(household_id).get("current_plan_id")


# ── store preferences ─────────────────────────────────────────────────────
def read_store_prefs(household_id: str) -> dict:
    d = _hh_dict(household_id)
    return (d.get("store_prefs", {}) if d else {}) or {}


def set_store_pref(household_id: str, item: str, store_name: str) -> None:
    key = (item or "").strip().lower()
    if not key:
        return
    _hh(household_id).set({"store_prefs": {key: store_name}}, merge=True)


# ── identity (phone -> household) ─────────────────────────────────────────
def resolve_household(phone: str) -> str:
    return get_household_for_phone(phone) or DEFAULT_HOUSEHOLD_ID


def get_household_for_phone(phone: str) -> Optional[str]:
    snap = _db().collection("phone_index").document(phone).get()
    return snap.to_dict().get("household_id") if snap.exists else None


def get_or_create_household(phone: str) -> str:
    db = _db()
    pref = db.collection("phone_index").document(phone)
    counter = db.collection("meta").document("counters")

    @firestore.transactional
    def _txn(txn):
        psnap = pref.get(transaction=txn)
        if psnap.exists:
            return psnap.to_dict()["household_id"]
        csnap = counter.get(transaction=txn)
        n = ((csnap.to_dict() or {}).get("households", 0) if csnap.exists else 0) + 1
        hid = f"h{n}"
        txn.set(counter, {"households": n}, merge=True)
        txn.set(pref, {"household_id": hid})
        return hid

    return _txn(db.transaction())


def map_phone(phone: str, household_id: str) -> None:
    _db().collection("phone_index").document(phone).set({"household_id": household_id})


def all_phone_household_pairs() -> list:
    return [(snap.id, snap.to_dict().get("household_id"))
            for snap in _db().collection("phone_index").stream()]


# ── invites + redeem attempts ─────────────────────────────────────────────
def put_invite(code: str, data: dict, now: float) -> None:
    # Expired invites are cleaned by a Firestore TTL policy on `expires`; redeem also
    # re-checks expiry, so no manual pruning needed here.
    _db().collection("invites").document(code).set(data)


def get_invite(code: str) -> Optional[dict]:
    snap = _db().collection("invites").document(code).get()
    return snap.to_dict() if snap.exists else None


def consume_invite(code: str, now: float) -> Optional[dict]:
    ref = _db().collection("invites").document(code)

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return None
        data = snap.to_dict()
        if data.get("expires", 0) <= now:
            return None
        txn.delete(ref)
        return data

    return _txn(_db().transaction())


def record_redeem_attempt(phone: str, window: float, now: float) -> int:
    ref = _db().collection("redeem_attempts").document(phone)

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        prev = (snap.to_dict().get("attempts", []) if snap.exists else [])
        attempts = [t for t in prev if now - t < window]
        attempts.append(now)
        txn.set(ref, {"attempts": attempts[-50:]})
        return len(attempts)

    return _txn(_db().transaction())


# ── inbound idempotency (atomic create) ───────────────────────────────────
def claim_sid(sid: str) -> bool:
    ref = _db().collection("processed_sids").document(sid)
    try:
        ref.create({"_ts": firestore.SERVER_TIMESTAMP})
        return True
    except gexc.AlreadyExists:
        return False


def release_sid(sid: str) -> None:
    """Undo a claim so a failed message can be re-processed on retry (deleting the marker
    lets the next attempt re-claim instead of being deduped away as 'already handled')."""
    _db().collection("processed_sids").document(sid).delete()
