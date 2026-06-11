"""M0 model tests — the onboarding gate and serialization round-trips."""
from app.models import GroceryItem, GroceryList, Profile


def test_onboarding_gate_blocks_when_incomplete():
    p = Profile(household_id="h1")
    assert not p.is_ready_to_onboard()
    assert set(p.missing_required()) == {
        "cuisines", "staples", "diet_type", "weekly_budget", "location",
    }


def test_onboarding_gate_passes_when_complete():
    p = Profile(
        household_id="h1",
        cuisines=["Indian"],
        staples=["rice", "roti"],
        diet_type="vegetarian",
        weekly_budget="3000",
        location="Pune, India",
    )
    assert p.is_ready_to_onboard()
    assert p.missing_required() == []


def test_grocery_list_round_trip():
    gl = GroceryList(list_id="L1", household_id="h1", items=[GroceryItem(name="paneer")])
    d = gl.model_dump()
    assert d["items"][0]["name"] == "paneer"
    assert d["items"][0]["status"] == "needed"  # default
    assert GroceryList(**d).items[0].name == "paneer"
