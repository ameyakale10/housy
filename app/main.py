"""Housy's web service (FastAPI).

- /chat              local TEST harness, gated by ENABLE_TEST_CHAT (off in prod — it
                     trusts a caller-supplied phone, so it must never be public)
- /webhook/whatsapp  Twilio inbound: verify signature, dedup SID, 200 fast, work in bg,
                     reply + relay shared-state changes to the partner's thread
- /tasks/weekly-nudge  token-protected endpoint an external cron hits weekly
"""
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from app import brain, config, identity, invites, present, store
from app.channels import whatsapp

logger = logging.getLogger("housy")
# User-facing copy for invite-redemption outcomes (shared by /chat + WhatsApp).
_INVITE_FAIL = {
    "rate_limited": "Too many invite-code attempts. Please wait a few minutes and try again.",
    "already_member": "You're already in a household with Housy. To switch, ask there to "
                      "remove you first.",
    "invalid": "That invite code is invalid or has expired. Ask your partner to text Housy "
               '"add my partner" for a fresh one.',
}


@asynccontextmanager
async def _lifespan(_app):
    missing = config.missing_prod_secrets()
    if missing:
        msg = "Missing/weak security config: " + ", ".join(missing)
        if config.HOUSY_ENV == "prod":
            raise RuntimeError(msg)  # refuse to boot a public deploy without secrets
        logger.warning("[dev] %s", msg)
    yield


app = FastAPI(title="Housy", lifespan=_lifespan)


class ChatIn(BaseModel):
    message: str
    phone: str = "+0000000000"  # stand-in sender for local testing


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatIn):
    """Local stand-in for WhatsApp. DISABLED unless ENABLE_TEST_CHAT is set, because it
    trusts a caller-supplied phone (no Twilio signature) and must not be public."""
    if not config.ENABLE_TEST_CHAT:
        raise HTTPException(status_code=404, detail="not found")
    inv = invites.maybe_redeem(body.message, body.phone)
    if inv is not None:
        if inv.get("ok"):
            return {"reply": f"Joined {inv['inviter']}'s household.", "household_id": inv["household_id"]}
        return {"reply": _INVITE_FAIL.get(inv["reason"], _INVITE_FAIL["invalid"]), "household_id": None}
    household_id = identity.resolve_or_create_household(body.phone)
    reply = brain.reply_to(body.message, household_id=household_id, speaker_phone=body.phone)
    return {"reply": reply, "household_id": household_id}


def _process_whatsapp(from_phone: str, body: str, media_url: str = None, media_type: str = None) -> None:
    """BackgroundTask entry: never let an exception vanish silently — always reply."""
    try:
        _handle_inbound(from_phone, body, media_url, media_type)
    except Exception:
        logger.exception("processing failed for %s", from_phone)
        try:
            whatsapp.send_message(from_phone, "Sorry, something went wrong on my end — please try again in a moment.")
        except Exception:
            pass


def _handle_inbound(from_phone: str, body: str, media_url: str, media_type: str) -> None:
    # Voice notes: transcribe to text. Other media (images) isn't supported yet.
    if media_url:
        if (media_type or "").startswith("audio"):
            audio, ctype = whatsapp.download_media(media_url)
            body = brain.transcribe(audio, ctype or media_type) or body
            if not body:
                whatsapp.send_message(from_phone, "Sorry, I couldn't make out that voice note — mind typing it or resending? 🙂")
                return
        else:
            whatsapp.send_message(from_phone, "I can't read photos or files yet (receipts are coming!). For now, please type or send a voice note 🙂")
            return

    # Invite codes are handled BEFORE household resolution (they change which household
    # this phone belongs to).
    inv = invites.maybe_redeem(body, from_phone)
    if inv is not None:
        if inv.get("ok"):
            hid, inviter = inv["household_id"], inv["inviter"]
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
        else:
            whatsapp.send_message(from_phone, _INVITE_FAIL.get(inv["reason"], _INVITE_FAIL["invalid"]))
        return

    household_id = identity.resolve_or_create_household(from_phone)
    result = brain.run_turn(body, household_id=household_id, speaker_phone=from_phone)
    whatsapp.send_message(from_phone, result["text"])

    # Cross-partner relay: tell the other partner what changed AND share the content.
    partner = identity.other_member_phone(household_id, from_phone)
    if partner:
        wrote = result.get("wrote", [])
        relay = whatsapp.build_relay(result.get("speaker"), wrote)
        if relay:
            msg = f"Housy: {relay}"
            if any(w in wrote for w in ("save_meal_plan", "save_grocery_list", "update_grocery_list")):
                content = present.plan_and_list(household_id)
                if content:
                    msg += "\n\n" + content
            try:
                whatsapp.send_message(partner, msg)
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

    from_phone = whatsapp.strip_prefix(params.get("From", ""))
    body = params.get("Body", "")
    num_media = int(params.get("NumMedia", "0") or 0)
    media_url = params.get("MediaUrl0") if num_media else None
    media_type = params.get("MediaContentType0") if num_media else None
    if not (from_phone and (body or media_url)):
        return Response(status_code=200)

    sid = params.get("MessageSid", "")
    if sid and not store.claim_sid(sid):
        return Response(status_code=200)  # duplicate retry — already handled

    background_tasks.add_task(_process_whatsapp, from_phone, body, media_url, media_type)
    return Response(status_code=200)


@app.post("/tasks/weekly-nudge")
def weekly_nudge(token: str = ""):
    """Hit by an external cron once a week. In production the nudge MUST be a registered
    WhatsApp template (24h-window rule)."""
    if not config.NUDGE_TOKEN or not hmac.compare_digest(token, config.NUDGE_TOKEN):
        raise HTTPException(status_code=403, detail="bad nudge token")
    sent = 0
    for phone, _hid in store.all_phone_household_pairs():
        try:
            whatsapp.send_message(phone, config.NUDGE_TEXT)
            sent += 1
        except Exception:
            pass
    return {"sent": sent}
