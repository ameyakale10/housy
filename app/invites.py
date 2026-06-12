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
"""
import datetime
import re
import secrets

from app import identity, store

TTL_SECONDS = 7 * 24 * 60 * 60      # 7 days
TTL_DAYS = 7
_INVITES = ("households", "invites.json")
_ATTEMPTS = ("households", "redeem_attempts.json")
# unambiguous: no 0/O/1/I
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_RE = re.compile(r"HOUSY-?([A-Z0-9]{6})(?![A-Z0-9])", re.IGNORECASE)
_ATTEMPT_WINDOW = 15 * 60
_MAX_ATTEMPTS = 5


def _now() -> float:
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _path(parts):
    return store.DATA_DIR / parts[0] / parts[1]


def _load_invites() -> dict:
    return store._read_json(_path(_INVITES)) or {}


def create_invite(household_id: str, created_by_phone: str):
    """Mint an invite code. Only a member of the household may invite."""
    prof = store.read_profile(household_id) or {}
    if not any(m.get("phone") == created_by_phone for m in prof.get("members", [])):
        return None
    code = "HOUSY-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
    with store.household_lock("__invites__"):
        data = {k: v for k, v in _load_invites().items() if v.get("expires", 0) > _now()}
        data[code] = {"household_id": household_id, "by": created_by_phone, "expires": _now() + TTL_SECONDS}
        store._write_json(_path(_INVITES), data)
    return code


def extract_code(text: str):
    m = _CODE_RE.search(text or "")
    return "HOUSY-" + m.group(1).upper() if m else None


def _register_attempt(phone: str) -> bool:
    """Record a redemption attempt; return True if the phone is now over the limit."""
    with store.household_lock("__invites__"):
        path = _path(_ATTEMPTS)
        data = store._read_json(path) or {}
        now = _now()
        attempts = [t for t in data.get(phone, []) if now - t < _ATTEMPT_WINDOW]
        attempts.append(now)
        data[phone] = attempts[-50:]
        store._write_json(path, data)
        return len(attempts) > _MAX_ATTEMPTS


def redeem(code: str, phone: str) -> dict:
    """Redeem a code. Returns:
      {"ok": True, "household_id", "inviter"}                       on success
      {"ok": False, "reason": "rate_limited"|"already_member"|"invalid"}  otherwise
    """
    if _register_attempt(phone):
        return {"ok": False, "reason": "rate_limited"}
    with store.household_lock("__invites__"):
        data = _load_invites()
        inv = data.get(code)
        if not inv or inv.get("expires", 0) <= _now():
            return {"ok": False, "reason": "invalid"}
        target = inv["household_id"]
        # Don't silently move a phone that already belongs to a different, onboarded household.
        index = store._read_json(store.DATA_DIR / "households" / "index.json") or {}
        current = index.get(phone)
        if current and current != target:
            if (store.read_profile(current) or {}).get("status") == "onboarded":
                return {"ok": False, "reason": "already_member"}
        del data[code]  # single-use
        store._write_json(_path(_INVITES), data)
    identity.link_phone(phone, target)
    inviter = identity.member_name(target, inv.get("by", "")) or "your partner"
    return {"ok": True, "household_id": target, "inviter": inviter}


def maybe_redeem(message: str, phone: str):
    """If the message contains a code, redeem it and return the result dict; else None."""
    code = extract_code(message)
    return redeem(code, phone) if code else None
