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
