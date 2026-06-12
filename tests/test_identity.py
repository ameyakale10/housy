"""Identity tests — the anti-pollution guarantees."""
import app.identity as identity
import app.store as store


def test_unknown_phones_get_isolated_households(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    a = identity.resolve_or_create_household("+111")
    b = identity.resolve_or_create_household("+222")
    assert a != b  # strangers never share a household


def test_same_phone_is_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    assert identity.resolve_or_create_household("+111") == identity.resolve_or_create_household("+111")


def test_link_phone_shares_household(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    identity.link_phone("+222", h)  # partner joins
    assert identity.resolve_or_create_household("+222") == h


def test_member_name_set_and_get(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    assert identity.member_name(h, "+111") is None  # not guessed
    identity.set_member_name(h, "+111", "Ameya")
    assert identity.member_name(h, "+111") == "Ameya"


def test_remove_from_household_keeps_household_with_remaining_members(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    identity.link_phone("+222", h)  # two members now
    identity.remove_from_household("+111", h)
    prof = store.read_profile(h)
    assert prof is not None  # household survives (a member with a phone remains)
    phones = [m.get("phone") for m in prof["members"]]
    assert "+111" not in phones and "+222" in phones  # only the one dropped


def test_remove_from_household_deletes_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")  # solo household
    identity.remove_from_household("+111", h)
    assert store.read_profile(h) is None  # no members left -> household removed
