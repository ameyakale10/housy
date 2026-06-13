"""Household invites — self-serve partner linking.

An existing (onboarded) member mints a short-lived, single-use code; the partner texts
that code to Housy from their OWN phone to join. That combination is the authorization:
only a member can create a code (consent), and only the partner, from their own verified
number, can redeem it (identity/possession).

Hardening:
- Codes are 6 chars from an unambiguous alphabet (~10^9 space), not 4 digits.
- Redemption is rate-limited per phone (brute-force defense).
- Redeem will NOT silently move a phone that already belongs to a different *onboarded*
  household.

All persistence goes through `store` (so it works on the file backend and Firestore alike);
this module holds only the invite *business logic*.
"""
import datetime
import re
import secrets

from app import identity, store

TTL_SECONDS = 7 * 24 * 60 * 60      # 7 days
TTL_DAYS = 7
# unambiguous: no 0/O/1/I
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_RE = re.compile(r"HOUSY-?([A-Z0-9]{6})(?![A-Z0-9])", re.IGNORECASE)
_ATTEMPT_WINDOW = 15 * 60
_MAX_ATTEMPTS = 5


def _now() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def create_invite(household_id: str, created_by_phone: str):
    """Mint an invite code. Only a member of the household may invite."""
    prof = store.read_profile(household_id) or {}
    if not any(m.get("phone") == created_by_phone for m in prof.get("members", [])):
        return None
    code = "HOUSY-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
    store.put_invite(
        code,
        {"household_id": household_id, "by": created_by_phone, "expires": _now() + TTL_SECONDS},
        _now(),
    )
    return code


def extract_code(text: str):
    m = _CODE_RE.search(text or "")
    return "HOUSY-" + m.group(1).upper() if m else None


def redeem(code: str, phone: str) -> dict:
    """Redeem a code. Returns:
      {"ok": True, "household_id", "inviter"}                       on success
      {"ok": False, "reason": "rate_limited"|"already_member"|"invalid"}  otherwise
    """
    if store.record_redeem_attempt(phone, _ATTEMPT_WINDOW, _now()) > _MAX_ATTEMPTS:
        return {"ok": False, "reason": "rate_limited"}

    now = _now()
    inv = store.get_invite(code)
    if not inv or inv.get("expires", 0) <= now:
        return {"ok": False, "reason": "invalid"}

    target = inv["household_id"]
    # Don't silently move a phone that already belongs to a different, onboarded household.
    current = store.get_household_for_phone(phone)
    if current and current != target:
        if (store.read_profile(current) or {}).get("status") == "onboarded":
            return {"ok": False, "reason": "already_member"}

    consumed = store.consume_invite(code, now)  # atomic single-use delete
    if not consumed:
        return {"ok": False, "reason": "invalid"}  # raced / just expired

    # Carry over the name they already gave Housy in their own solo household, then tidy
    # that now-empty household away so they don't linger in two places.
    joiner_name = identity.member_name(current, phone) if current else None
    identity.link_phone(phone, target, name=joiner_name)
    if current and current != target:
        identity.remove_from_household(phone, current)

    inviter = identity.member_name(target, consumed.get("by", "")) or "your partner"
    return {"ok": True, "household_id": target, "inviter": inviter}


def maybe_redeem(message: str, phone: str):
    """If the message contains a code, redeem it and return the result dict; else None."""
    code = extract_code(message)
    return redeem(code, phone) if code else None
