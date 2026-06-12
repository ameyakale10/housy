"""Per-item store preference tests + grouped presentation."""
import app.identity as identity
import app.present as present
import app.store as store
import app.tools as tools


def _h(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return identity.resolve_or_create_household("+111")


def test_set_item_store_remembers(tmp_path, monkeypatch):
    h = _h(tmp_path, monkeypatch)
    tools.build_dispatch(h, "+111", [])["set_item_store"](item="Paneer", store="Indian Store")
    assert store.read_store_prefs(h)["paneer"] == "Indian Store"


def test_grocery_list_inherits_store_pref(tmp_path, monkeypatch):
    h = _h(tmp_path, monkeypatch)
    d = tools.build_dispatch(h, "+111", [])
    d["set_item_store"](item="paneer", store="Indian Store")
    d["save_grocery_list"](items=[
        {"name": "Paneer", "category": "Dairy"},      # store from affinity
        {"name": "Milk", "store": "Costco"},          # store from the model
        {"name": "Bread"},                            # unknown -> None ("any")
    ])
    stores = {i["name"]: i.get("store") for i in store.current_grocery_list(h)["items"]}
    assert stores["Paneer"] == "Indian Store"
    assert stores["Milk"] == "Costco"
    assert stores["Bread"] is None


def test_present_groups_by_store(tmp_path, monkeypatch):
    h = _h(tmp_path, monkeypatch)
    tools.build_dispatch(h, "+111", []).get("save_grocery_list")(items=[
        {"name": "Paneer", "store": "Indian Store"},
        {"name": "Milk", "store": "Costco"},
    ])
    out = present.format_grocery_list(store.current_grocery_list(h))
    assert "Indian Store" in out and "Costco" in out and "Paneer" in out
