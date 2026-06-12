"""Housy's file-based store (JSON) — the single seam over persistence.

Everything is scoped by household_id under data/<hid>/. Structured entities are JSON
(they map 1:1 onto a future DB), the memory summary is prose, and the turn history is
JSONL. Swapping to Firestore later (M4) means changing only this file.

Layout:
    data/<hid>/profile.json
    data/<hid>/meal-plans/<plan_id>.json
    data/<hid>/grocery-lists/<list_id>.json
    data/<hid>/bills/<bill_id>.json
    data/<hid>/memory/summary.md        (prose)
    data/<hid>/memory/history.jsonl
    data/households/index.json          (phone -> household_id)

Concurrency: a per-household *reentrant* lock guards the WHOLE read-modify-write of
mutating ops, not just the write. FastAPI runs sync handlers / BackgroundTasks in a
threadpool, so two partners messaging at once execute on different threads; a
write-only lock would still let both read stale state and the second clobber the
first (the lost-update bug). We use threading.RLock (correct for threaded sync code)
rather than asyncio.Lock.
"""
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, List, Optional

from app.config import DEFAULT_HOUSEHOLD_ID, PROJECT_ROOT

DATA_DIR = Path(PROJECT_ROOT) / "data"

# ── per-household locks ───────────────────────────────────────────────────
_locks: dict = {}
_locks_guard = threading.Lock()


def _lock_for(household_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(household_id)
        if lock is None:
            lock = threading.RLock()
            _locks[household_id] = lock
        return lock


@contextmanager
def household_lock(household_id: str):
    """Guard a whole read-modify-write for one household."""
    lock = _lock_for(household_id)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


# ── atomic JSON io ────────────────────────────────────────────────────────
def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # atomic rename on the same filesystem


def _hid_dir(household_id: str) -> Path:
    return DATA_DIR / household_id


# ── profile ───────────────────────────────────────────────────────────────
def read_profile(household_id: str = DEFAULT_HOUSEHOLD_ID) -> Optional[dict]:
    return _read_json(_hid_dir(household_id) / "profile.json")


def write_profile(household_id: str, profile: dict) -> None:
    with household_lock(household_id):
        _write_json(_hid_dir(household_id) / "profile.json", profile)


def update_profile(household_id: str, mutate: Callable[[dict], dict]) -> dict:
    """Atomic read-modify-write of the profile (closes the partner lost-update bug).

    `mutate` receives the current profile (or a minimal stub if none exists yet) and
    returns the updated one; the whole read->mutate->write runs under the household lock,
    so two partners saving at the same instant can't clobber each other's fields.
    """
    with household_lock(household_id):
        current = _read_json(_hid_dir(household_id) / "profile.json") or {"household_id": household_id}
        updated = mutate(current)
        _write_json(_hid_dir(household_id) / "profile.json", updated)
        return updated


# ── meal plans / grocery lists / bills ────────────────────────────────────
def save_meal_plan(household_id: str, plan: dict) -> None:
    with household_lock(household_id):
        _write_json(_hid_dir(household_id) / "meal-plans" / f"{plan['plan_id']}.json", plan)


def save_grocery_list(household_id: str, glist: dict) -> None:
    with household_lock(household_id):
        _write_json(_hid_dir(household_id) / "grocery-lists" / f"{glist['list_id']}.json", glist)


def read_grocery_list(household_id: str, list_id: str) -> Optional[dict]:
    return _read_json(_hid_dir(household_id) / "grocery-lists" / f"{list_id}.json")


def update_grocery_list(
    household_id: str, list_id: str, mutate: Callable[[dict], dict]
) -> Optional[dict]:
    """Atomic read-modify-write of a grocery list (closes the lost-update bug).

    `mutate` receives the current list dict and returns the updated one; the whole
    read->mutate->write runs under the household lock.
    """
    with household_lock(household_id):
        path = _hid_dir(household_id) / "grocery-lists" / f"{list_id}.json"
        current = _read_json(path)
        if current is None:
            return None
        updated = mutate(current)
        _write_json(path, updated)
        return updated


def save_bill(household_id: str, bill: dict) -> None:
    with household_lock(household_id):
        _write_json(_hid_dir(household_id) / "bills" / f"{bill['bill_id']}.json", bill)


# ── memory ────────────────────────────────────────────────────────────────
def read_memory_summary(household_id: str = DEFAULT_HOUSEHOLD_ID) -> str:
    path = _hid_dir(household_id) / "memory" / "summary.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_memory_summary(household_id: str, text: str) -> None:
    with household_lock(household_id):
        path = _hid_dir(household_id) / "memory" / "summary.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def append_turn(household_id: str, turn: dict) -> None:
    """Append one speaker-tagged turn to the merged per-household history."""
    with household_lock(household_id):
        path = _hid_dir(household_id) / "memory" / "history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def read_history(household_id: str = DEFAULT_HOUSEHOLD_ID, n: int = 12) -> List[dict]:
    """Last `n` turns of the merged per-household history (most recent last)."""
    path = _hid_dir(household_id) / "memory" / "history.jsonl"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    turns = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            turns.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return turns


# ── identity ──────────────────────────────────────────────────────────────
def resolve_household(phone: str) -> str:
    """Map an inbound phone number to a household_id (default for unknown)."""
    index = _read_json(DATA_DIR / "households" / "index.json") or {}
    return index.get(phone, DEFAULT_HOUSEHOLD_ID)


# ── lightweight per-household state (e.g. the current grocery list) ────────
def set_current_list(household_id: str, list_id: str) -> None:
    with household_lock(household_id):
        path = _hid_dir(household_id) / "state.json"
        state = _read_json(path) or {}
        state["current_list_id"] = list_id
        _write_json(path, state)


def current_list_id(household_id: str) -> Optional[str]:
    state = _read_json(_hid_dir(household_id) / "state.json") or {}
    return state.get("current_list_id")


def set_current_plan(household_id: str, plan_id: str) -> None:
    with household_lock(household_id):
        path = _hid_dir(household_id) / "state.json"
        state = _read_json(path) or {}
        state["current_plan_id"] = plan_id
        _write_json(path, state)


def current_plan_id(household_id: str) -> Optional[str]:
    state = _read_json(_hid_dir(household_id) / "state.json") or {}
    return state.get("current_plan_id")


def latest_meal_plan(household_id: str) -> Optional[dict]:
    """The household's current meal plan (the tracked id), falling back to the newest
    file by mtime if no id is tracked yet."""
    pid = current_plan_id(household_id)
    if pid:
        p = _read_json(_hid_dir(household_id) / "meal-plans" / f"{pid}.json")
        if p:
            return p
    d = _hid_dir(household_id) / "meal-plans"
    if not d.exists():
        return None
    files = list(d.glob("*.json"))
    if not files:
        return None
    return _read_json(max(files, key=lambda p: p.stat().st_mtime))


def current_grocery_list(household_id: str) -> Optional[dict]:
    """The household's active grocery list (or None)."""
    lid = current_list_id(household_id)
    return read_grocery_list(household_id, lid) if lid else None


# ── item -> store preferences (which store an item is usually bought from) ──
def read_store_prefs(household_id: str) -> dict:
    """Map of lowercased item name -> store ('any' means no preference)."""
    return _read_json(_hid_dir(household_id) / "store_prefs.json") or {}


def set_store_pref(household_id: str, item: str, store_name: str) -> None:
    key = (item or "").strip().lower()
    if not key:
        return
    with household_lock(household_id):
        path = _hid_dir(household_id) / "store_prefs.json"
        prefs = _read_json(path) or {}
        prefs[key] = store_name
        _write_json(path, prefs)


# ── inbound idempotency (dedup Twilio retries) ────────────────────────────
def claim_sid(sid: str) -> bool:
    """Atomically claim a Twilio message SID. Returns True if newly seen (process it),
    False if it's a duplicate retry (skip)."""
    with household_lock("__sids__"):
        path = DATA_DIR / "processed-sids.json"
        data = _read_json(path) or {"sids": []}
        if sid in data["sids"]:
            return False
        data["sids"] = (data["sids"] + [sid])[-500:]  # keep the last 500
        _write_json(path, data)
        return True


def release_sid(sid: str) -> None:
    """Undo a claim so a failed message can be re-processed on retry. Called when
    processing raised after the SID was claimed — without this the retry would see the
    SID as 'already handled' and silently drop the message."""
    with household_lock("__sids__"):
        path = DATA_DIR / "processed-sids.json"
        data = _read_json(path) or {"sids": []}
        if sid in data["sids"]:
            data["sids"] = [s for s in data["sids"] if s != sid]
            _write_json(path, data)


def all_phone_household_pairs() -> list:
    """Every (phone, household_id) mapping — used to fan out the weekly nudge."""
    index = _read_json(_index_path()) or {}
    return list(index.items())


# ── phone → household index (used by identity) ────────────────────────────
def _index_path() -> Path:
    return DATA_DIR / "households" / "index.json"


def get_household_for_phone(phone: str) -> Optional[str]:
    return (_read_json(_index_path()) or {}).get(phone)


def get_or_create_household(phone: str) -> str:
    """Atomically return this phone's household, or allocate a fresh isolated one."""
    with household_lock("__index__"):
        index = _read_json(_index_path()) or {}
        hid = index.get(phone)
        if hid:
            return hid
        taken = set(index.values())
        n = 1
        while f"h{n}" in taken:
            n += 1
        hid = f"h{n}"
        index[phone] = hid
        _write_json(_index_path(), index)
        return hid


def map_phone(phone: str, household_id: str) -> None:
    """Atomically point a phone at a household (used to join a partner)."""
    with household_lock("__index__"):
        index = _read_json(_index_path()) or {}
        index[phone] = household_id
        _write_json(_index_path(), index)


# ── invites + redeem attempts (used by invites) ───────────────────────────
def _invites_path() -> Path:
    return DATA_DIR / "households" / "invites.json"


def _attempts_path() -> Path:
    return DATA_DIR / "households" / "redeem_attempts.json"


def put_invite(code: str, data: dict, now: float) -> None:
    """Store an invite, pruning any expired ones first."""
    with household_lock("__invites__"):
        live = {k: v for k, v in (_read_json(_invites_path()) or {}).items()
                if v.get("expires", 0) > now}
        live[code] = data
        _write_json(_invites_path(), live)


def get_invite(code: str) -> Optional[dict]:
    return (_read_json(_invites_path()) or {}).get(code)


def consume_invite(code: str, now: float) -> Optional[dict]:
    """Atomically remove and return an invite if present and unexpired (single-use)."""
    with household_lock("__invites__"):
        invites = _read_json(_invites_path()) or {}
        inv = invites.get(code)
        if not inv or inv.get("expires", 0) <= now:
            return None
        del invites[code]
        _write_json(_invites_path(), invites)
        return inv


def record_redeem_attempt(phone: str, window: float, now: float) -> int:
    """Record a redeem attempt; return how many attempts are in the current window."""
    with household_lock("__invites__"):
        data = _read_json(_attempts_path()) or {}
        attempts = [t for t in data.get(phone, []) if now - t < window]
        attempts.append(now)
        data[phone] = attempts[-50:]
        _write_json(_attempts_path(), data)
        return len(attempts)


# ── backend selection ──────────────────────────────────────────────────────
# Everything above is the FILE backend (local dev + tests). When configured for
# Firestore, rebind every public name to the Firestore backend (same signatures),
# so the rest of the app is unchanged.
import app.config as _config  # noqa: E402

if _config.STORAGE_BACKEND == "firestore":
    from app.storage import firestore_backend as _fb  # noqa: E402

    _PUBLIC = (
        "household_lock", "read_profile", "write_profile", "update_profile",
        "save_meal_plan", "latest_meal_plan",
        "save_grocery_list", "read_grocery_list", "update_grocery_list", "current_grocery_list",
        "save_bill",
        "read_memory_summary", "write_memory_summary", "append_turn", "read_history",
        "resolve_household",
        "set_current_list", "current_list_id", "set_current_plan", "current_plan_id",
        "read_store_prefs", "set_store_pref",
        "claim_sid", "release_sid", "all_phone_household_pairs",
        "get_household_for_phone", "get_or_create_household", "map_phone",
        "put_invite", "get_invite", "consume_invite", "record_redeem_attempt",
    )
    for _n in _PUBLIC:
        globals()[_n] = getattr(_fb, _n)
