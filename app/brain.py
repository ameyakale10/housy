"""Housy's brain: turns an incoming message into a reply using Gemini.

M0: single-shot reply that reads the couple's JSON profile + memory summary into the
system prompt, so Housy already 'knows' the couple. M1 adds the stateful tool-calling
loop and the merged speaker-tagged history. Channel-agnostic: any channel calls
reply_to().
"""
import json

from google import genai
from google.genai import types

from app import config, store

_client = None


def _get_client() -> "genai.Client":
    global _client
    if _client is None:
        if config.USE_VERTEX:
            # Vertex AI — bills to your Google Cloud credits. Auth via ADC
            # (gcloud auth application-default login); no key in code.
            if not config.GCP_PROJECT:
                raise RuntimeError(
                    "GCP_PROJECT is not set. Set it in .env and run "
                    "`gcloud auth application-default login`."
                )
            _client = genai.Client(
                vertexai=True,
                project=config.GCP_PROJECT,
                location=config.GCP_LOCATION,
            )
        else:
            if not config.GEMINI_API_KEY:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
                )
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _format_profile(profile) -> str:
    if not profile:
        return "(no profile saved yet — status: not-onboarded)"
    return json.dumps(profile, indent=2, ensure_ascii=False)


def _system_prompt(household_id: str) -> str:
    profile = store.read_profile(household_id)
    memory = store.read_memory_summary(household_id) or "(no memory yet)"
    status = (profile or {}).get("status", "not-onboarded")
    return f"""You are Housy, a warm, practical household assistant for a couple.
You talk to them over WhatsApp, so keep replies short, friendly, and easy to act on
(no long essays). You help with meal planning, grocery lists, store visits, and
grocery bills.

What you know about this couple (their saved profile, JSON):
---
{_format_profile(profile)}
---

Your long-term memory summary:
---
{memory}
---

If status is 'not-onboarded' (currently: {status}), gently begin onboarding: ask about
their cuisine and daily staples, diet and allergies, and rough weekly budget — a couple
of questions at a time, not all at once. Otherwise, help with whatever they ask."""


def reply_to(user_message: str, household_id: str = config.DEFAULT_HOUSEHOLD_ID) -> str:
    """Generate Housy's reply to one user message (M0: single-shot, no tools yet)."""
    client = _get_client()
    resp = client.models.generate_content(
        model=config.MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(system_instruction=_system_prompt(household_id)),
    )
    return (resp.text or "").strip() or "(Housy had no reply — try rephrasing?)"
