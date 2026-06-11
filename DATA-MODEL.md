# Housy — Data Model

This is the spine of Housy: what it remembers, and how the pieces relate. The live store
is **JSON files under `data/<household_id>/`** (see `app/store.py` and `app/models.py`),
chosen so code can read fields reliably and the data maps 1:1 onto a future database. The
memory summary stays prose (`summary.md`) and turn history is JSONL. Each shape here is a
**prototype of a future database table**, so when Housy scales this maps over with no
rethinking. (The entity field lists below describe the JSON shapes; the older `_template.md`
examples were removed in favor of the Pydantic models.)

Design principles:
- **One source of truth per fact.** Preferences live in the profile; prices live in
  bills. Nothing is duplicated, only referenced.
- **Everything is linked by IDs**, so a grocery list knows which meal plan it came
  from, a bill knows which store visit it belongs to, etc.
- **Append, don't overwrite history.** Old meal plans and bills are kept — that history
  is what powers budgeting, price memory, and "what did we buy last time."

---

## The entities (future DB tables)

### 1. household  →  `couple-profile.md`
The couple and their standing preferences. One per household.
- `household_id`, `members` [{name, phone, role}], `created_at`
- profile: cuisine(s), daily staples, spice level, diet type, allergies, dislikes,
  weekly budget, cooking time, kitchen equipment
- `phone` numbers double as the **login** — an incoming WhatsApp/SMS number maps to a
  household.

### 2. meal_plan  →  `data/meal-plans/<week-of>.md`
One week of planned meals.
- `plan_id`, `household_id`, `week_of` (Monday's date), `status` (draft|active|archived)
- `days`: 7 × { date, breakfast, lunch, dinner }, each meal = { title, recipe_ref?, notes }
- `created_at`

### 3. grocery_list  →  `data/grocery-lists/<id>.md`
A shopping list. Usually generated from a meal plan, but can be standalone.
- `list_id`, `household_id`, `status` (open|shopping|done)
- `source`: { type: meal_plan | manual, plan_id? }
- `items`: [{ name, qty, unit, category, status: needed|bought, added_by }]
- `created_at`

### 4. store_visit  →  `data/store-visits/<date-store>.md`
A real trip to a store. The event that ties a list to a bill.
- `visit_id`, `household_id`, `date`, `store_name`, `store_location`
- `list_id` (what they went to buy), `bill_id` (the receipt), `notes`

### 5. bill  →  `data/bills/<date-store>.md`
An itemized receipt. The richest data — drives budgeting and price memory.
- `bill_id`, `household_id`, `visit_id`, `date`, `store_name`, `currency`
- `line_items`: [{ name, qty, unit, unit_price, total, category, grocery_item_match? }]
- `subtotal`, `tax`, `total`

### 6. conversation memory  →  `data/memory/summary.md` (+ `conversation-log.md`)
What makes Housy feel like it *remembers* across chats.
- `conversation-log.md`: raw running log of messages {ts, from, channel, text}
- `summary.md`: a maintained short summary of durable facts & decisions, so Housy
  recalls context without re-reading every old message.

---

## How they connect

```
household (couple-profile)
   │  owns
   ├──► meal_plan ──generates──► grocery_list
   │                                  │  shopped during
   │                                  ▼
   └──────────────────────────► store_visit ──has──► bill ──has──► line_items
                                                                       │
                                          (derived, not stored) ───────┘
                                          price_history: ingredient → [{date, store, unit_price}]
                                          budget: sum(bill.total) over time
```

- **price_history** and **budget** are *derived* by reading across bills — never stored
  separately. Ask "is milk cheaper at X?" → scan `line_items`. Ask "how much did we
  spend this month?" → sum `bill.total`.

---

## Mapping to a real database (later)

| Markdown prototype        | Future table(s)                         |
|---------------------------|-----------------------------------------|
| `couple-profile.md`       | `households`, `household_members`       |
| `data/meal-plans/*.md`    | `meal_plans`, `meal_plan_entries`       |
| `data/grocery-lists/*.md` | `grocery_lists`, `grocery_items`        |
| `data/store-visits/*.md`  | `store_visits`                          |
| `data/bills/*.md`         | `bills`, `bill_line_items`              |
| `data/memory/*.md`        | `messages`, `household_memory`          |

Human-readable filenames (dates, store slugs) are the prototype's "primary keys";
they become real IDs (e.g. UUIDs) in the database.

---

## What reads/writes this

Each Housy **skill** owns part of the model:
- `meal-planning` → reads `couple-profile.md`; writes a `meal_plan` and its `grocery_list`.
- *(future)* `grocery-list` → edits a list (add/remove/mark bought).
- *(future)* `log-bill` → records a `store_visit` + `bill` from a receipt.
- *(future)* `budget` → reads bills; reports spend & price trends.
