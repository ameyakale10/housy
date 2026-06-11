"""Housy's brain (M1): a stateful, tool-calling reply loop.

Per turn it: loads the household's profile + memory summary + merged speaker-tagged
history, runs a capped Gemini function-calling loop (the model writes via tools), then
persists the turn and best-effort refreshes the summary if anything durable changed.

Guardrails:
- household_id is passed in (resolved from the verified phone) and bound into the tool
  dispatch — the model can never touch another household's data.
- Low temperature + a truthfulness-first system prompt to curb hallucination.
- The model is told to ASK for the speaker's name, never invent it.
"""
import datetime
import json

from google import genai
from google.genai import types

from app import config, identity, store, tools

MAX_TOOL_ITERS = 8
TEMPERATURE = 0.3

_client = None


def _get_client() -> "genai.Client":
    global _client
    if _client is None:
        if config.USE_VERTEX:
            if not config.GCP_PROJECT:
                raise RuntimeError(
                    "GCP_PROJECT is not set. Set it in .env and run "
                    "`gcloud auth application-default login`."
                )
            _client = genai.Client(
                vertexai=True, project=config.GCP_PROJECT, location=config.GCP_LOCATION,
            )
        else:
            if not config.GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY is not set (USE_VERTEX is false).")
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _system_prompt(household_id: str, speaker_name) -> str:
    profile = store.read_profile(household_id)
    memory = store.read_memory_summary(household_id) or "(no memory yet)"
    status = (profile or {}).get("status", "not-onboarded")
    profile_json = json.dumps(profile, indent=2, ensure_ascii=False) if profile else "(none)"
    who = speaker_name or "UNKNOWN — you have not been told this person's name yet"
    return f"""You are Housy, a warm, practical household assistant for a couple. You talk
to them over WhatsApp, so keep replies short, friendly, and easy to act on. You help with
meal planning, grocery lists, and grocery spending.

WHO YOU ARE TALKING TO:
- The current speaker's saved name: {who}.
- If the name is UNKNOWN, make your FIRST priority a friendly ask for their name, then
  call set_speaker_name. NEVER guess or make up a name.
- This household is a couple (up to two people). History lines are prefixed with the
  speaker's name so you know who said what. Address the current speaker.

TRUTHFULNESS (critical):
- Only state facts that appear in the profile, the memory summary, or this conversation.
- If you do not know something, ASK. Never invent preferences, names, past meals,
  purchases, or prices.
- When the couple tells you something durable (a preference, a plan, a spend), SAVE it by
  calling the right tool. Do not merely claim you saved it — actually call the tool.

ONBOARDING:
- If the profile status is 'not-onboarded' (currently: {status}), gently collect their
  cuisine(s), daily staples, diet & allergies, and rough weekly budget — a couple of
  questions at a time, not all at once — and call save_profile. Status flips to
  'onboarded' automatically once those four are present.

MEAL PLANNING:
- When they ask you to plan meals and the profile is complete, be decisive: build a
  concrete plan from their cuisine, daily staples, diet and budget (never include
  allergens). You MUST persist it in the SAME turn by calling save_meal_plan AND
  save_grocery_list — do this BEFORE or ALONGSIDE telling them the plan. Do not wait for
  them to confirm before saving; they can always edit it afterwards. Only ask a
  clarifying question if the profile is missing something essential.

THIS HOUSEHOLD'S PROFILE (JSON):
{profile_json}

YOUR MEMORY SUMMARY:
{memory}
"""


def _build_contents(history, speaker_label: str, message: str):
    contents = []
    for turn in history:
        text = turn.get("text", "")
        if turn.get("speaker") == "housy":
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
        else:
            who = turn.get("speaker") or "Unknown"
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"{who}: {text}")]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"{speaker_label}: {message}")]))
    return contents


def _update_summary(client, household_id: str) -> None:
    """Best-effort memory refresh. history.jsonl stays the source of truth, so a
    failure here never costs data and never blocks the reply."""
    try:
        history = store.read_history(household_id, n=20)
        profile = store.read_profile(household_id) or {}
        transcript = "\n".join(f"{t.get('speaker', '?')}: {t.get('text', '')}" for t in history)
        prompt = (
            "Update Housy's long-term memory summary for this household. Include ONLY "
            "durable facts the couple actually stated (preferences, plans, decisions, "
            "names, spending). Do NOT invent anything. Keep it under 180 words, in short "
            "bullet points.\n\nPROFILE JSON:\n" + json.dumps(profile, ensure_ascii=False)
            + "\n\nRECENT CONVERSATION:\n" + transcript
        )
        resp = client.models.generate_content(
            model=config.MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        text = (resp.text or "").strip()
        if text:
            store.write_memory_summary(household_id, text)
    except Exception:
        pass  # best-effort by design


def reply_to(message: str,
             household_id: str = config.DEFAULT_HOUSEHOLD_ID,
             speaker_phone: str = "local-test") -> str:
    """Generate Housy's reply to one message, persisting state via tools."""
    client = _get_client()
    speaker_name = identity.member_name(household_id, speaker_phone)
    speaker_label = speaker_name or "Unknown"

    wrote: list = []
    dispatch = tools.build_dispatch(household_id, speaker_phone, wrote)
    cfg = types.GenerateContentConfig(
        system_instruction=_system_prompt(household_id, speaker_name),
        tools=[tools.gemini_tool()],
        temperature=TEMPERATURE,
    )
    contents = _build_contents(store.read_history(household_id, n=12), speaker_label, message)

    reply_text = "(I got a bit tangled up — could you say that once more?)"
    for _ in range(MAX_TOOL_ITERS):
        resp = client.models.generate_content(model=config.MODEL, contents=contents, config=cfg)
        calls = resp.function_calls or []
        if not calls:
            reply_text = (resp.text or "").strip() or reply_text
            break
        contents.append(resp.candidates[0].content)
        parts = []
        for fc in calls:
            fn = dispatch.get(fc.name)
            args = dict(fc.args or {})
            result = fn(**args) if fn else {"error": f"unknown tool {fc.name}"}
            parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=parts))

    # Persist the turn (speaker-tagged), then refresh memory if anything was saved.
    store.append_turn(household_id, {"ts": _now(), "speaker": speaker_label, "channel": "chat", "text": message})
    store.append_turn(household_id, {"ts": _now(), "speaker": "housy", "channel": "chat", "text": reply_text})
    if wrote:
        _update_summary(client, household_id)
    return reply_text
