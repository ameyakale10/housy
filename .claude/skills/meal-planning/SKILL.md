---
name: meal-planning
description: Plan a full week (breakfast, lunch, dinner) of meals for a couple and produce a consolidated grocery list. Reads the couple's preferences from couple-profile.md, and onboards them first if that profile isn't filled in yet. Use when the user asks for a meal plan, a weekly menu, what to cook this week, or a grocery/shopping list.
---

# Meal Planning

Housy's meal-planning skill. It plans **7 days of breakfast, lunch, and dinner**
for a couple, then turns that plan into **one consolidated grocery list**.

It is **profile-driven**: instead of asking the same questions every time, it reads
the couple's saved preferences from `couple-profile.md` at the Housy project root. If
that profile hasn't been filled in yet, it onboards the couple first.

## Step 1 — Load (or create) the couple's profile

1. Read `couple-profile.md` from the Housy project root.
2. Look at the `status:` line.
   - If `status: onboarded`, skip to **Step 2**.
   - If `status: not-onboarded` (or the file is missing / mostly blank), run onboarding:

### Onboarding (only when the profile isn't filled in)

Interview the couple one topic at a time — keep it friendly and short. Ask about:
- Household: names, how many people usually eat, who cooks and how confident.
- **Cuisine & staples** (most important for a good plan): primary cuisine(s)
  (e.g. Indian, Mexican, Thai, Italian), their **daily staple foods**
  (e.g. rice, roti/chapati, tortillas, noodles, bread), spice level, and how much
  variety vs. familiar favorites they want.
- Diet: diet type, allergies (always avoid), strong dislikes, other cuisines to mix in.
- Practical constraints: realistic weeknight & weekend cooking time, weekly grocery
  budget, and notable kitchen equipment.

Then **write their answers back into `couple-profile.md`**, filling in each field and
setting `status: onboarded`. Confirm with the couple before moving on.

## Step 2 — Plan the week

Using the profile, create a 7-day plan covering **breakfast, lunch, and dinner**.
Honor these rules, in priority order:

1. **Never** include anything in their allergies list.
2. Center meals on their **primary cuisine(s) and daily staples** — the plan should
   feel like food they actually eat, not generic recipes. (e.g. an Indian-staple
   couple should see roti/rice-based meals, not pasta every night.)
3. Respect diet type, dislikes, and spice level.
4. Keep weeknight meals within their stated cooking time; save involved dishes for
   the weekend.
5. Add gentle variety so the week isn't repetitive, while staying within their
   "variety vs. favorites" preference.
6. Reuse ingredients across meals where sensible to reduce waste and cost.

Present the plan as a clear **7-day table** (rows = days, columns = breakfast / lunch
/ dinner). Keep dish names short; offer to expand any into a full recipe on request.

## Step 3 — Build the grocery list

From the finalized plan, produce **one consolidated shopping list**:
- Combine the same ingredient across meals into a single line with a total quantity
  (e.g. don't list "onion" five times — sum it).
- Group by store section: Produce, Grains & staples, Proteins, Dairy, Pantry/spices,
  Other.
- Assume common staples already on hand (salt, oil, basic spices) unless the profile
  says otherwise — but call out anything they likely need to restock.

## Step 4 — Wrap up

- Show the plan and the grocery list together.
- Ask if they want to swap any meal, adjust for a busier day, or save the plan.
- If they ask to change a meal, update both the plan **and** the grocery list so the
  two stay in sync.

## Notes for the future (don't build yet)

- A later version can estimate cost (a tool-use exercise) and pull recipes from a
  saved recipe collection (a RAG exercise). Keep this version profile + plan + list.
