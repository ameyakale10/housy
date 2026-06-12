"""DESTRUCTIVE one-time reset of Housy's production Firestore data.

Wipes ALL household data and identity mappings so every phone starts fresh:
  - households/*           (incl. meal_plans / grocery_lists / bills / messages subcollections)
  - phone_index/*          (unlinks every phone)
  - processed_sids/*       (inbound-dedup markers)
  - redeem_attempts/*      (invite rate-limit counters)
  - invites/*              (outstanding invite codes)
  - meta/counters          (reset so the next household is h1 again)

Prints counts before deleting. Run with the prod Firestore env.
"""
import sys

from app import store
from app.storage import firestore_backend as fb

TOP_LEVEL = ["phone_index", "processed_sids", "redeem_attempts", "invites"]


def main():
    db = fb._db()

    # 1. Households — use delete_household so subcollections go too.
    hids = [snap.id for snap in db.collection("households").stream()]
    print("households to delete:", hids)
    for hid in hids:
        store.delete_household(hid)
        print(f"  deleted household {hid}")

    # 2. Flat identity / bookkeeping collections.
    for coll in TOP_LEVEL:
        docs = list(db.collection(coll).stream())
        print(f"{coll}: deleting {len(docs)} docs")
        for d in docs:
            d.reference.delete()

    # 3. Reset the household counter so the next phone gets h1.
    db.collection("meta").document("counters").delete()
    print("meta/counters reset")

    # Verify empty.
    print("--- AFTER ---")
    print("households:", [s.id for s in db.collection("households").stream()])
    print("phone_index:", [s.id for s in db.collection("phone_index").stream()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
