"""Housy's web service (FastAPI).

- /chat              local test harness (resolves household from phone, runs the brain)
- /webhook/whatsapp  Twilio inbound: verify signature, dedup SID, 200 fast, work in bg,
                     reply + relay shared-state changes to the partner's thread
- /tasks/weekly-nudge  token-protected endpoint an external cron hits weekly
"""
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from app import brain, config, identity, store
from app.channels import whatsapp

app = FastAPI(title="Housy")


class ChatIn(BaseModel):
    message: str
    phone: str = "+0000000000"  # stand-in sender for local testing


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatIn):
    """Local stand-in for WhatsApp. The phone identifies the person; the household is
    derived from it (never from the message), so data stays isolated per household."""
    household_id = identity.resolve_or_create_household(body.phone)
    reply = brain.reply_to(body.message, household_id=household_id, speaker_phone=body.phone)
    return {"reply": reply, "household_id": household_id}


def _process_whatsapp(from_phone: str, body: str) -> None:
    """Heavy work (Gemini loop + sends) — runs in a BackgroundTask so the webhook can
    200 immediately and we never hit Twilio's timeout."""
    household_id = identity.resolve_or_create_household(from_phone)
    result = brain.run_turn(body, household_id=household_id, speaker_phone=from_phone)
    whatsapp.send_message(from_phone, result["text"])

    # Cross-partner relay: tell the other partner about shared-state changes.
    partner = identity.other_member_phone(household_id, from_phone)
    if partner:
        relay = whatsapp.build_relay(result.get("speaker"), result.get("wrote", []))
        if relay:
            try:
                whatsapp.send_message(partner, f"Housy: {relay}")
            except Exception:
                pass  # delivery can fail outside the 24h window; non-fatal


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    url = whatsapp.public_url(request.url.path, str(request.url))
    if not whatsapp.verify_signature(url, params, signature):
        raise HTTPException(status_code=403, detail="invalid Twilio signature")

    sid = params.get("MessageSid", "")
    if sid and not store.claim_sid(sid):
        return Response(status_code=200)  # duplicate retry — already handled

    from_phone = whatsapp.strip_prefix(params.get("From", ""))
    body = params.get("Body", "")
    if from_phone and body:
        background_tasks.add_task(_process_whatsapp, from_phone, body)
    return Response(status_code=200)


@app.post("/tasks/weekly-nudge")
def weekly_nudge(token: str = ""):
    """Hit by an external cron once a week. In production the nudge MUST be a registered
    WhatsApp template (24h-window rule)."""
    if not config.NUDGE_TOKEN or token != config.NUDGE_TOKEN:
        raise HTTPException(status_code=403, detail="bad nudge token")
    sent = 0
    for phone, _hid in store.all_phone_household_pairs():
        try:
            whatsapp.send_message(phone, config.NUDGE_TEXT)
            sent += 1
        except Exception:
            pass
    return {"sent": sent}
