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
    hid = store.get_or_create_household(phone)
    # Seed a not-onboarded profile with this phone as the first member.
    if store.read_profile(hid) is None:
        store.write_profile(hid, Profile(household_id=hid, members=[Member(phone=phone)]).model_dump())
    return hid


def link_phone(phone: str, household_id: str, name: str = None) -> None:
    """Map an additional phone (the partner) to an existing household so the two share
    state. Adds them to the member list (atomically), carrying their known name if we
    have one — so a partner who already told Housy their name isn't asked again."""
    store.map_phone(phone, household_id)

    def _add(prof):
        members = prof.setdefault("members", [])
        for m in members:
            if m.get("phone") == phone:
                if name and not m.get("name"):
                    m["name"] = name  # fill in a name we now know
                return prof
        members.append({"name": name or "", "phone": phone, "role": ""})
        return prof

    store.update_profile(household_id, _add)


def remove_from_household(phone: str, household_id: str) -> None:
    """Drop a phone from a household. If no members with a phone remain, delete the whole
    household — this clears the orphaned solo household left behind when someone joins
    their partner's household instead of keeping their own."""
    prof = store.read_profile(household_id)
    if not prof:
        return
    members = [m for m in prof.get("members", []) if m.get("phone") != phone]
    if not any(m.get("phone") for m in members):
        store.delete_household(household_id)
    else:
        prof["members"] = members
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
    """Save the speaker's name on their member record (keyed by phone), ATOMICALLY — so a
    concurrent link_phone (partner joining) can't be clobbered by this write, which would
    silently drop the just-added member."""

    def _set(prof):
        members = prof.setdefault("members", [])
        for m in members:
            if m.get("phone") == phone:
                m["name"] = name
                break
        else:
            members.append({"name": name, "phone": phone, "role": ""})
        return prof

    store.update_profile(household_id, _set)
