"""One-time cleanup for the partner-join bug (pre-fix data).

Before the join fix, a partner who texted Housy before redeeming an invite was left
with a blank-name entry in the couple's household AND an orphaned solo household. This
script repairs the existing production data to match what the fixed code now produces:

  1. Fill in the partner's name on the couple's household (if blank).
  2. Delete the orphaned solo household.

Idempotent and read-first: prints before/after and skips anything already clean.
Run with the prod Firestore env (GCP_PROJECT set, default database).
"""
import sys

from app import store

COUPLE_HID = "h1"
ORPHAN_HID = "h2"
PARTNER_PHONE = "+12268811741"
PARTNER_NAME = "Swati"


def main():
    couple = store.read_profile(COUPLE_HID)
    orphan = store.read_profile(ORPHAN_HID)
    print(f"BEFORE {COUPLE_HID} members:", [(m.get('name'), m.get('phone')) for m in (couple or {}).get('members', [])])
    print(f"BEFORE {ORPHAN_HID} exists:", orphan is not None)

    if not couple:
        print(f"!! {COUPLE_HID} not found — aborting, nothing changed.")
        return 1

    # 1. Fill the partner's name on the couple's household if it's blank.
    changed = False
    for m in couple.get("members", []):
        if m.get("phone") == PARTNER_PHONE and not m.get("name"):
            m["name"] = PARTNER_NAME
            changed = True
    if changed:
        store.write_profile(COUPLE_HID, couple)
        print(f"-> set {PARTNER_PHONE} name to {PARTNER_NAME!r} in {COUPLE_HID}")
    else:
        print(f"-> {COUPLE_HID} name already set; no change")

    # 2. Delete the orphan solo household (only if the partner is safely in the couple one).
    in_couple = any(m.get("phone") == PARTNER_PHONE for m in couple.get("members", []))
    mapped = store.get_household_for_phone(PARTNER_PHONE)
    if orphan is not None and in_couple and mapped == COUPLE_HID:
        store.delete_household(ORPHAN_HID)
        print(f"-> deleted orphan household {ORPHAN_HID}")
    elif orphan is None:
        print(f"-> {ORPHAN_HID} already gone; no change")
    else:
        print(f"!! NOT deleting {ORPHAN_HID}: in_couple={in_couple} phone_maps_to={mapped} — verify manually")

    print(f"AFTER  {COUPLE_HID} members:", [(m.get('name'), m.get('phone')) for m in (store.read_profile(COUPLE_HID) or {}).get('members', [])])
    print(f"AFTER  {ORPHAN_HID} exists:", store.read_profile(ORPHAN_HID) is not None)
    print(f"phone {PARTNER_PHONE} -> household:", store.get_household_for_phone(PARTNER_PHONE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
