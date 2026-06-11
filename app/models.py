"""Pydantic models for Housy's data — the single source of truth.

These mirror DATA-MODEL.md and serialize straight to the JSON store (store.py),
will back the Gemini tool schemas (M1), and map 1:1 onto the future DB rows (M4).

Python 3.9 note: `list[str]` / `dict[..]` work at runtime (PEP 585); we use
Optional[...] (not `X | None`) for 3.9 compatibility.
"""
from typing import ClassVar, List, Literal, Optional

from pydantic import BaseModel, Field


class Member(BaseModel):
    name: str = ""
    phone: str = ""
    role: str = ""


class Profile(BaseModel):
    """The couple/household preferences.

    `status` only flips to 'onboarded' once the required fields are present —
    see `missing_required()` / `is_ready_to_onboard()` (the onboarding gate).
    """
    household_id: str
    members: List[Member] = Field(default_factory=list)
    cuisines: List[str] = Field(default_factory=list)      # e.g. ["Indian"]
    staples: List[str] = Field(default_factory=list)       # e.g. ["rice", "roti"]
    spice_level: Optional[str] = None                      # mild | medium | hot
    diet_type: Optional[str] = None                        # omnivore | vegetarian | ...
    allergies: List[str] = Field(default_factory=list)
    dislikes: List[str] = Field(default_factory=list)
    weekly_budget: Optional[str] = None
    weeknight_time: Optional[str] = None
    weekend_time: Optional[str] = None
    equipment: List[str] = Field(default_factory=list)
    notes: str = ""
    status: Literal["not-onboarded", "onboarded"] = "not-onboarded"

    # The onboarding gate: these must be non-empty before status may flip.
    REQUIRED_FOR_ONBOARDING: ClassVar[tuple] = (
        "cuisines", "staples", "diet_type", "weekly_budget",
    )

    def missing_required(self) -> List[str]:
        return [f for f in self.REQUIRED_FOR_ONBOARDING if not getattr(self, f)]

    def is_ready_to_onboard(self) -> bool:
        return not self.missing_required()


class DayPlan(BaseModel):
    date: str = ""
    breakfast: Optional[str] = None
    lunch: Optional[str] = None
    dinner: Optional[str] = None


class MealPlan(BaseModel):
    plan_id: str
    household_id: str
    week_of: str = ""                                      # Monday's date (YYYY-MM-DD)
    status: Literal["draft", "active", "archived"] = "draft"
    days: List[DayPlan] = Field(default_factory=list)
    created_at: str = ""


class GroceryItem(BaseModel):
    name: str
    qty: Optional[str] = None
    unit: Optional[str] = None
    category: str = "Other"
    status: Literal["needed", "bought"] = "needed"
    added_by: str = ""


class GroceryList(BaseModel):
    list_id: str
    household_id: str
    status: Literal["open", "shopping", "done"] = "open"
    source_type: Literal["meal_plan", "manual"] = "manual"
    source_plan_id: Optional[str] = None
    items: List[GroceryItem] = Field(default_factory=list)
    created_at: str = ""


class Bill(BaseModel):
    """Text-only spend log for the MVP (no OCR line items yet)."""
    bill_id: str
    household_id: str
    date: str = ""
    store_name: str = ""
    currency: str = ""
    total: Optional[float] = None
    line_items: List[dict] = Field(default_factory=list)   # empty in MVP
    created_at: str = ""


class Turn(BaseModel):
    """One conversation turn. `speaker` lets the merged, per-household history
    stay attributable (which partner, or Housy, said it)."""
    ts: str
    speaker: str = ""                                      # partner name / phone / "housy"
    channel: str = "chat"
    text: str = ""
