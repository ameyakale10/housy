"""Tool dispatch tests — structured writes + the onboarding gate + no cross-household
pollution. These exercise the guardrails without calling Gemini."""
import app.identity as identity
import app.store as store
import app.tools as tools


def test_save_profile_onboarding_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    wrote = []
    d = tools.build_dispatch(h, "+111", wrote)

    r = d["save_profile"](cuisines=["Indian"])           # partial
    assert r["status"] == "not-onboarded"
    assert "save_profile" in wrote

    r = d["save_profile"](staples=["rice"], diet_type="vegetarian", weekly_budget="3000")
    assert r["status"] == "onboarded"                    # gate satisfied
    assert store.read_profile(h)["status"] == "onboarded"


def test_set_speaker_name(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    tools.build_dispatch(h, "+111", [])["set_speaker_name"](name="Ameya")
    assert identity.member_name(h, "+111") == "Ameya"


def test_grocery_save_then_update(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    d = tools.build_dispatch(h, "+111", [])
    d["save_grocery_list"](items=[{"name": "paneer", "category": "Dairy"}])
    lid = store.current_list_id(h)
    assert lid
    d["update_grocery_list"](add=["tomatoes"], mark_bought=["paneer"])
    items = store.read_grocery_list(h, lid)["items"]
    names = {i["name"] for i in items}
    assert {"paneer", "tomatoes"} <= names
    assert any(i["name"] == "paneer" and i["status"] == "bought" for i in items)


def test_log_spend(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    r = tools.build_dispatch(h, "+111", [])["log_spend"](amount=2400, store_name="BigBasket", currency="INR")
    assert r["ok"] and r["total"] == 2400


def test_no_cross_household_pollution(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    ha = identity.resolve_or_create_household("+111")
    hb = identity.resolve_or_create_household("+222")
    # write a full profile into A
    tools.build_dispatch(ha, "+111", [])["save_profile"](
        cuisines=["Indian"], staples=["rice"], diet_type="vegetarian", weekly_budget="3000")
    # B is untouched — the model bound to A literally cannot reach B
    pb = store.read_profile(hb)
    assert pb["status"] == "not-onboarded"
    assert pb.get("cuisines", []) == []
