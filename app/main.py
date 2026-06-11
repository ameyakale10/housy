"""Housy's web service (FastAPI).

- /chat              local test harness (resolves household from phone, runs the brain)
- /webhook/whatsapp  Twilio inbound: verify signature, dedup SID, 200 fast, work in bg,
                     reply + relay shared-state changes to the partner's thread
- /tasks/weekly-nudge  token-protected endpoint an external cron hits weekly
"""
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from app import brain, config, identity, invites, store
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
    joined = invites.maybe_redeem(body.message, body.phone)
    if joined:
        hid, inviter = joined
        return {"reply": f"Joined {inviter}'s household ({hid}).", "household_id": hid}
    household_id = identity.resolve_or_create_household(body.phone)
    reply = brain.reply_to(body.message, household_id=household_id, speaker_phone=body.phone)
    return {"reply": reply, "household_id": household_id}


def _process_whatsapp(from_phone: str, body: str, media_url: str = None, media_type: str = None) -> None:
    """Heavy work (Gemini loop + sends) — runs in a BackgroundTask so the webhook can
    200 immediately and we never hit Twilio's timeout."""
    # Voice notes: transcribe to text and proceed. Other media (images) isn't supported
    # yet (receipt OCR is a later milestone).
    if media_url:
        if (media_type or "").startswith("audio"):
            try:
                audio, ctype = whatsapp.download_media(media_url)
                body = brain.transcribe(audio, ctype or media_type) or body
            except Exception:
                pass
            if not body:
                whatsapp.send_message(from_phone, "Sorry, I couldn't make out that voice note — mind typing it or resending? 🙂")
                return
        else:
            whatsapp.send_message(from_phone, "I can't read photos or files yet (receipts are coming!). For now, please type or send a voice note 🙂")
            return

    # A partner joining via invite code is handled before the brain (it changes which
    # household this phone belongs to).
    joined = invites.maybe_redeem(body, from_phone)
    if joined:
        hid, inviter = joined
        msg = (f"🎉 You've joined {inviter}'s Housy household! You now share meal plans, "
               f"grocery lists and spending. What's your name?")
        store.append_turn(hid, {"speaker": from_phone, "channel": "whatsapp", "text": body})
        store.append_turn(hid, {"speaker": "housy", "channel": "whatsapp", "text": msg})
        whatsapp.send_message(from_phone, msg)
        partner = identity.other_member_phone(hid, from_phone)
        if partner:
            try:
                whatsapp.send_message(partner, "Housy: Your partner just joined your household 🎉")
            except Exception:
                pass
        return

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
    num_media = int(params.get("NumMedia", "0") or 0)
    media_url = params.get("MediaUrl0") if num_media else None
    media_type = params.get("MediaContentType0") if num_media else None
    if from_phone and (body or media_url):
        background_tasks.add_task(_process_whatsapp, from_phone, body, media_url, media_type)
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
