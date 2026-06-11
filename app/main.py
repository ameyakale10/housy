"""Housy's web service (FastAPI).

Slice 1: a local test endpoint so we can talk to Housy's brain before wiring up
WhatsApp. Slice 2 will add the Twilio WhatsApp webhook that calls the same brain.
"""
from fastapi import FastAPI
from pydantic import BaseModel

from app import brain

app = FastAPI(title="Housy")


class ChatIn(BaseModel):
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatIn):
    """Local test endpoint — stands in for WhatsApp until the channel is wired up."""
    return {"reply": brain.reply_to(body.message)}
