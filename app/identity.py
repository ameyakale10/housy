"""Identity: who is messaging, and which household they belong to.

The unique key for a person is their PHONE NUMBER (the verified WhatsApp sender).
A household groups people; both partners' phones map to the same household_id, which
is how they share state. Everything downstream is scoped by that household_id, so two
households can never see or pollute each other's data.

Guardrail: household_id is derived ONLY here, from the (verified) phone. It is never
taken from message content and never exposed to the LLM as a tool argument.
"""
from app import store
from app.models import Member, Profile


def resolve_or_create_household(phone: str) -> str:
    """Return the household for this phone, creating a fresh isolated one if unknown.

    An unknown phone gets its OWN new household (never the couple's), so a stranger
    can never land in someone else's data. Partners are joined explicitly via
    link_phone().
    """
    index_path = store.DATA_DIR / "households" / "index.json"
    with store.household_lock("__index__"):
        index = store._read_json(index_path) or {}
        hid = index.get(phone)
        if hid:
            return hid
        taken = set(index.values())
        n = 1
        while f"h{n}" in taken:
            n += 1
        hid = f"h{n}"
        index[phone] = hid
        store._write_json(index_path, index)
    # Seed a not-onboarded profile with this phone as the first member.
    if store.read_profile(hid) is None:
        store.write_profile(hid, Profile(household_id=hid, members=[Member(phone=phone)]).model_dump())
    return hid


def link_phone(phone: str, household_id: str) -> None:
    """Map an additional phone (the partner) to an existing household so the two
    share state. Used to put both partners in the same household for the MVP."""
    index_path = store.DATA_DIR / "households" / "index.json"
    with store.household_lock("__index__"):
        index = store._read_json(index_path) or {}
        index[phone] = household_id
        store._write_json(index_path, index)
    prof = store.read_profile(household_id) or Profile(household_id=household_id).model_dump()
    if not any(m.get("phone") == phone for m in prof.get("members", [])):
        prof.setdefault("members", []).append({"name": "", "phone": phone, "role": ""})
        store.write_profile(household_id, prof)


def member_name(household_id: str, phone: str):
    """The saved name for this phone in this household, or None if not set yet."""
    prof = store.read_profile(household_id) or {}
    for m in prof.get("members", []):
        if m.get("phone") == phone:
            return m.get("name") or None
    return None


def other_member_phone(household_id: str, phone: str):
    """The partner's phone in this household (the other member with a phone), or None."""
    prof = store.read_profile(household_id) or {}
    for m in prof.get("members", []):
        p = m.get("phone")
        if p and p != phone:
            return p
    return None


def set_member_name(household_id: str, phone: str, name: str) -> None:
    """Save the speaker's name on their member record (keyed by phone)."""
    prof = store.read_profile(household_id) or Profile(household_id=household_id).model_dump()
    members = prof.setdefault("members", [])
    for m in members:
        if m.get("phone") == phone:
            m["name"] = name
            break
    else:
        members.append({"name": name, "phone": phone, "role": ""})
    store.write_profile(household_id, prof)
