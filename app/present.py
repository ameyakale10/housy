"""Human-facing formatting for plans and grocery lists (WhatsApp-friendly).

Used by the cross-partner relay, the meal-plan safety net, and anywhere Housy needs to
show the real saved state. Grocery lists group by STORE when items carry a store, else
by category — so a couple sees what to buy where.
"""
from collections import OrderedDict

from app import store


def format_meal_plan(plan) -> str:
    if not plan or not plan.get("days"):
        return ""
    lines = [f"🍽️ Meal plan (week of {plan.get('week_of') or 'this week'}):"]
    for d in plan["days"]:
        lines.append(f"• {d.get('date') or '?'}: {d.get('dinner') or '-'}")
    return "\n".join(lines)


def format_grocery_list(glist) -> str:
    if not glist or not glist.get("items"):
        return ""
    groups = OrderedDict()
    for i in glist["items"]:
        key = i.get("store") or i.get("category") or "Other"
        groups.setdefault(key, []).append(i)
    lines = ["🛒 Grocery list:"]
    for key, items in groups.items():
        lines.append(f"*{key}*")
        for i in items:
            mark = " ✓" if i.get("status") == "bought" else ""
            qty = f" ({i['qty']})" if i.get("qty") else ""
            lines.append(f"  - {i.get('name')}{qty}{mark}")
    return "\n".join(lines)


def plan_and_list(household_id: str) -> str:
    """The household's current plan + grocery list, formatted together."""
    parts = []
    p = format_meal_plan(store.latest_meal_plan(household_id))
    g = format_grocery_list(store.current_grocery_list(household_id))
    if p:
        parts.append(p)
    if g:
        parts.append(g)
    return "\n\n".join(parts)
