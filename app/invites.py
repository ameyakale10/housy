"""Household invites — self-serve partner linking.

An existing (onboarded) member mints a short-lived, single-use code; the partner texts
that code to Housy from their OWN phone to join. That combination is the authorization:
only a member can create a code (consent), and only the partner, from their own verified
number, can redeem it (identity/possession). This replaces any manual phone-mapping.
"""
import datetime
import re
import secrets

from app import identity, store

TTL_SECONDS = 15 * 60
_INVITES_PATH = ("households", "invites.json")
_CODE_RE = re.compile(r"HOUSY-?(\d{4})", re.IGNORECASE)


def _now() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _path():
    return store.DATA_DIR / _INVITES_PATH[0] / _INVITES_PATH[1]


def _load() -> dict:
    return store._read_json(_path()) or {}


def create_invite(household_id: str, created_by_phone: str):
    """Mint an invite code. Only a member of the household may invite. Returns the code
    string, or None if the caller isn't a member."""
    prof = store.read_profile(household_id) or {}
    if not any(m.get("phone") == created_by_phone for m in prof.get("members", [])):
        return None
    code = "HOUSY-" + str(secrets.randbelow(9000) + 1000)  # 4 digits
    with store.household_lock("__invites__"):
        data = {k: v for k, v in _load().items() if v.get("expires", 0) > _now()}  # prune
        data[code] = {"household_id": household_id, "by": created_by_phone, "expires": _now() + TTL_SECONDS}
        store._write_json(_path(), data)
    return code


def extract_code(text: str):
    m = _CODE_RE.search(text or "")
    return "HOUSY-" + m.group(1) if m else None


def redeem(code: str, phone: str):
    """Redeem a code: link `phone` to the inviting household, burn the code (single-use).
    Returns (household_id, inviter_name) on success, else None (unknown/expired code)."""
    with store.household_lock("__invites__"):
        data = _load()
        inv = data.get(code)
        if not inv or inv.get("expires", 0) <= _now():
            return None
        del data[code]  # single-use
        store._write_json(_path(), data)
    household_id = inv["household_id"]
    identity.link_phone(phone, household_id)
    inviter = identity.member_name(household_id, inv.get("by", "")) or "your partner"
    return household_id, inviter


def maybe_redeem(message: str, phone: str):
    """If the message contains a valid invite code, redeem it. Returns
    (household_id, inviter_name) or None."""
    code = extract_code(message)
    return redeem(code, phone) if code else None
