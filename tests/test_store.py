"""M0 store tests — JSON round-trips, atomic read-modify-write, history, and the
concurrency guarantee (no lost updates under the per-household lock)."""
import threading

import app.store as store


def test_profile_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.write_profile("h1", {"household_id": "h1", "status": "not-onboarded"})
    got = store.read_profile("h1")
    assert got["household_id"] == "h1"
    assert got["status"] == "not-onboarded"


def test_read_missing_profile_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    assert store.read_profile("nobody") is None


def test_grocery_atomic_update(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.save_grocery_list("h1", {"list_id": "L1", "household_id": "h1", "items": []})

    def add_paneer(lst):
        lst["items"].append({"name": "paneer", "category": "Dairy", "status": "needed"})
        return lst

    updated = store.update_grocery_list("h1", "L1", add_paneer)
    assert updated is not None
    assert any(i["name"] == "paneer" for i in store.read_grocery_list("h1", "L1")["items"])


def test_history_append_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    for i in range(5):
        store.append_turn("h1", {"ts": str(i), "speaker": "A", "text": f"msg{i}"})
    turns = store.read_history("h1", n=2)
    assert [t["text"] for t in turns] == ["msg3", "msg4"]


def test_concurrent_updates_no_lost_update(tmp_path, monkeypatch):
    """20 threads each append one item; the atomic lock must keep all 20."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.save_grocery_list("h1", {"list_id": "L1", "household_id": "h1", "items": []})

    def add(name):
        store.update_grocery_list("h1", "L1", lambda lst: {**lst, "items": lst["items"] + [{"name": name}]})

    threads = [threading.Thread(target=add, args=(f"item{i}",)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items = store.read_grocery_list("h1", "L1")["items"]
    assert len(items) == 20  # no lost updates


def test_resolve_household_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    assert store.resolve_household("+10000000000") == "h1"  # unknown → default
