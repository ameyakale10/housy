"""Housy's tools: Gemini function declarations + the server-bound dispatch.

KEY GUARDRAIL: the function *declarations* the model sees expose only business
fields (cuisines, items, amount, ...). They do NOT expose household_id. The dispatch
callables are built per request with household_id + speaker_phone captured in a
closure, so the model can only ever write to the household it is already scoped to.
It literally cannot address another household's data.
"""
import datetime
import uuid
from typing import Callable, Dict, List

from google.genai import types

from app import identity, invites, store
from app.models import Profile

# Categories used to group a grocery list.
_CATEGORIES = "Produce, Grains & staples, Proteins, Dairy, Pantry/spices, Other"


# ── small schema helpers ──────────────────────────────────────────────────
def _s(t, **kw):
    return types.Schema(type=t, **kw)


def _str(desc=""):
    return _s(types.Type.STRING, description=desc)


def _arr_str(desc=""):
    return _s(types.Type.ARRAY, items=_str(), description=desc)


def _obj(properties, required=None):
    return _s(types.Type.OBJECT, properties=properties, required=required or [])


# ── declarations (what the model sees) ────────────────────────────────────
def _declarations() -> List[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name="set_speaker_name",
            description="Save the name of the person you are CURRENTLY talking to. "
            "Call this as soon as they tell you their name. Never guess a name.",
            parameters=_obj({"name": _str("The person's first name")}, ["name"]),
        ),
        types.FunctionDeclaration(
            name="create_household_invite",
            description="Generate an invite code so the speaker's PARTNER can join this "
            "household and share meal plans, lists and spending. Call this when a member "
            "asks to add their partner/spouse. Then tell them the code and that their "
            "partner should text that code to Housy from their own phone to join.",
            parameters=_obj({}),
        ),
        types.FunctionDeclaration(
            name="save_profile",
            description="Save or update the household's food preferences. Call whenever "
            "the couple shares any preference. Include ONLY the fields you actually "
            "learned in this conversation; omit the rest. When you learn their location, "
            "ALSO set `currency` by inferring it from that location (e.g. India -> INR, "
            "USA -> USD). Status flips to 'onboarded' once cuisines, staples, diet_type, "
            "weekly_budget and location are set.",
            parameters=_obj({
                "cuisines": _arr_str("Primary cuisines, e.g. ['Indian']"),
                "staples": _arr_str("Daily staples, e.g. ['rice','roti']"),
                "diet_type": _str("omnivore | vegetarian | vegan | pescatarian | mixed"),
                "allergies": _arr_str("Must-always-avoid foods"),
                "dislikes": _arr_str("Foods to avoid when possible"),
                "spice_level": _str("mild | medium | hot"),
                "weekly_budget": _str("Rough weekly grocery budget"),
                "location": _str("Their city/area, e.g. 'Pune, India' — for currency + nearby stores"),
                "currency": _str("Currency code inferred from location, e.g. INR, USD"),
                "weeknight_time": _str("Realistic weeknight cooking time"),
                "equipment": _arr_str("Notable kitchen equipment"),
                "stores": _arr_str("Their go-to stores, e.g. ['Costco','Indian grocery store']"),
            }),
        ),
        types.FunctionDeclaration(
            name="save_meal_plan",
            description="Save a meal plan the couple has agreed to. Provide the days.",
            parameters=_obj({
                "week_of": _str("Monday's date, YYYY-MM-DD, if known"),
                "days": _s(types.Type.ARRAY, items=_obj({
                    "day": _str("e.g. Mon"),
                    "breakfast": _str(),
                    "lunch": _str(),
                    "dinner": _str(),
                })),
            }, ["days"]),
        ),
        types.FunctionDeclaration(
            name="save_grocery_list",
            description="Save a consolidated grocery list (usually derived from a meal "
            f"plan). Group each item into a category ({_CATEGORIES}).",
            parameters=_obj({
                "items": _s(types.Type.ARRAY, items=_obj({
                    "name": _str(),
                    "qty": _str("quantity + unit, e.g. '500 g'"),
                    "category": _str(),
                    "store": _str("Preferred store for this item, or 'any'"),
                }, ["name"])),
            }, ["items"]),
        ),
        types.FunctionDeclaration(
            name="set_item_store",
            description="Remember which store the couple buys a specific item from. Use "
            "'any' if it can be bought anywhere. Call this whenever they tell you where "
            "they get something (e.g. 'we buy paneer from the Indian store').",
            parameters=_obj({
                "item": _str("The grocery item, e.g. 'paneer'"),
                "store": _str("Store name, or 'any'"),
            }, ["item", "store"]),
        ),
        types.FunctionDeclaration(
            name="update_grocery_list",
            description="Edit the couple's current grocery list: add items, remove "
            "items, or mark items as bought. Use the item names.",
            parameters=_obj({
                "add": _arr_str("Item names to add"),
                "remove": _arr_str("Item names to remove"),
                "mark_bought": _arr_str("Item names to mark bought"),
            }),
        ),
        types.FunctionDeclaration(
            name="log_spend",
            description="Record a grocery spend the couple reports as text "
            "(e.g. 'spent 2400 at BigBasket'). No receipt/OCR — just the total.",
            parameters=_obj({
                "amount": _s(types.Type.NUMBER, description="Total amount spent"),
                "store_name": _str("Where they shopped"),
                "currency": _str("e.g. INR, USD"),
                "date": _str("YYYY-MM-DD if known"),
            }, ["amount"]),
        ),
    ]


def gemini_tool() -> types.Tool:
    return types.Tool(function_declarations=_declarations())


# ── dispatch (bound to one household; the model can't reach another) ──────
def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:4]}"


def build_dispatch(household_id: str, speaker_phone: str, wrote: List[str]) -> Dict[str, Callable]:
    """Return the tool name -> callable map, with household_id + speaker bound.

    `wrote` is appended to whenever a tool actually persists something, so the brain
    knows to refresh the memory summary.
    """

    def set_speaker_name(name: str = "", **_):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "empty name"}
        identity.set_member_name(household_id, speaker_phone, name)
        wrote.append("set_speaker_name")
        return {"ok": True, "saved_name": name}

    def create_household_invite(**_):
        code = invites.create_invite(household_id, speaker_phone)
        if not code:
            return {"ok": False, "error": "only an existing household member can invite"}
        return {"ok": True, "code": code, "expires_minutes": 15,
                "instructions": "Your partner should text this code to Housy from their own phone."}

    def save_profile(**fields):
        existing = store.read_profile(household_id) or {"household_id": household_id}
        merged = dict(existing)
        for k, v in fields.items():
            if v not in (None, "", []):
                merged[k] = v
        merged["household_id"] = household_id
        p = Profile(**merged)
        if p.is_ready_to_onboard():
            p.status = "onboarded"
        store.write_profile(household_id, p.model_dump())
        wrote.append("save_profile")
        return {"ok": True, "status": p.status, "still_missing": p.missing_required()}

    def set_item_store(**kw):
        item = (kw.get("item") or "").strip()
        store_name = kw.get("store") or "any"
        if not item:
            return {"ok": False, "error": "no item"}
        store.set_store_pref(household_id, item, store_name)
        return {"ok": True, "item": item, "store": store_name}

    def save_meal_plan(week_of: str = "", days=None, **_):
        days = days or []
        plan = {
            "plan_id": _gen_id("plan"),
            "household_id": household_id,
            "week_of": week_of or "",
            "status": "active",
            "days": [{
                "date": d.get("day", ""),
                "breakfast": d.get("breakfast"),
                "lunch": d.get("lunch"),
                "dinner": d.get("dinner"),
            } for d in days],
            "created_at": _now(),
        }
        store.save_meal_plan(household_id, plan)
        wrote.append("save_meal_plan")
        return {"ok": True, "plan_id": plan["plan_id"], "days": len(plan["days"])}

    def save_grocery_list(items=None, **_):
        items = items or []
        prefs = store.read_store_prefs(household_id)
        built = []
        for i in items:
            name = i.get("name", "")
            if not name:
                continue
            built.append({
                "name": name,
                "qty": i.get("qty"),
                "category": i.get("category", "Other"),
                "store": i.get("store") or prefs.get(name.strip().lower()),
                "status": "needed",
                "added_by": speaker_phone,
            })
        glist = {
            "list_id": _gen_id("list"),
            "household_id": household_id,
            "status": "open",
            "source_type": "meal_plan",
            "items": built,
            "created_at": _now(),
        }
        store.save_grocery_list(household_id, glist)
        store.set_current_list(household_id, glist["list_id"])
        wrote.append("save_grocery_list")
        return {"ok": True, "list_id": glist["list_id"], "items": len(built)}

    def update_grocery_list(add=None, remove=None, mark_bought=None, **_):
        list_id = store.current_list_id(household_id)
        if not list_id:
            return {"ok": False, "error": "no current grocery list to edit"}

        def mutate(lst):
            items = lst.get("items", [])
            for name in (add or []):
                items.append({"name": name, "qty": None, "category": "Other",
                              "status": "needed", "added_by": speaker_phone})
            if remove:
                rem = {r.lower() for r in remove}
                items = [i for i in items if i.get("name", "").lower() not in rem]
            if mark_bought:
                mb = {m.lower() for m in mark_bought}
                for i in items:
                    if i.get("name", "").lower() in mb:
                        i["status"] = "bought"
            lst["items"] = items
            return lst

        updated = store.update_grocery_list(household_id, list_id, mutate)
        wrote.append("update_grocery_list")
        return {"ok": updated is not None, "items": len((updated or {}).get("items", []))}

    def log_spend(amount=None, store_name: str = "", currency: str = "", date: str = "", **_):
        if not currency:  # fall back to the household's location-derived currency
            currency = (store.read_profile(household_id) or {}).get("currency", "") or ""
        bill = {
            "bill_id": _gen_id("bill"),
            "household_id": household_id,
            "date": date or _now()[:10],
            "store_name": store_name,
            "currency": currency,
            "total": amount,
            "line_items": [],
            "created_at": _now(),
        }
        store.save_bill(household_id, bill)
        wrote.append("log_spend")
        return {"ok": True, "bill_id": bill["bill_id"], "total": amount, "store": store_name}

    return {
        "set_speaker_name": set_speaker_name,
        "create_household_invite": create_household_invite,
        "set_item_store": set_item_store,
        "save_profile": save_profile,
        "save_meal_plan": save_meal_plan,
        "save_grocery_list": save_grocery_list,
        "update_grocery_list": update_grocery_list,
        "log_spend": log_spend,
    }
