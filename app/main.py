"""Housy's web service (FastAPI).

M1: /chat is the local test harness — it resolves the household from the caller's
phone (the same way the WhatsApp webhook will in M2) and runs the stateful brain.
"""
from fastapi import FastAPI
from pydantic import BaseModel

from app import brain, identity

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
