"""M2 WhatsApp tests — signature gate, SID dedup, relay text, partner lookup."""
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import app.config as config
import app.identity as identity
import app.main as main
import app.store as store
from app.channels import whatsapp

TOKEN = "test-auth-token"
URL = "http://testserver/webhook/whatsapp"


def _form(**extra):
    f = {"From": "whatsapp:+15551230000", "Body": "hi", "MessageSid": "SM123"}
    f.update(extra)
    return f


def test_build_relay():
    assert "grocery list" in whatsapp.build_relay("Ameya", ["update_grocery_list"])
    assert whatsapp.build_relay("Ameya", ["set_speaker_name"]) == ""  # nothing to relay


def test_other_member_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    h = identity.resolve_or_create_household("+111")
    identity.link_phone("+222", h)
    assert identity.other_member_phone(h, "+111") == "+222"
    assert identity.other_member_phone(h, "+222") == "+111"


def test_claim_sid_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    assert store.claim_sid("SMabc") is True
    assert store.claim_sid("SMabc") is False  # retry


def test_verify_signature(monkeypatch):
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    params = _form()
    sig = RequestValidator(TOKEN).compute_signature(URL, params)
    assert whatsapp.verify_signature(URL, params, sig) is True
    assert whatsapp.verify_signature(URL, params, "bogus") is False


def test_webhook_rejects_bad_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    client = TestClient(main.app)
    r = client.post("/webhook/whatsapp", data=_form(), headers={"X-Twilio-Signature": "bad"})
    assert r.status_code == 403


def test_webhook_accepts_valid_signature_and_dedups(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    calls = []
    monkeypatch.setattr(main, "_process_whatsapp", lambda *a: calls.append(a))

    client = TestClient(main.app)
    params = _form()
    sig = RequestValidator(TOKEN).compute_signature(URL, params)
    headers = {"X-Twilio-Signature": sig}

    r1 = client.post("/webhook/whatsapp", data=params, headers=headers)
    r2 = client.post("/webhook/whatsapp", data=params, headers=headers)  # duplicate SID
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls == [("+15551230000", "hi", None, None)]  # processed exactly once


def test_webhook_routes_voice_note(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    calls = []
    monkeypatch.setattr(main, "_process_whatsapp", lambda *a: calls.append(a))
    client = TestClient(main.app)
    params = {
        "From": "whatsapp:+15551230000", "Body": "", "MessageSid": "SMvoice",
        "NumMedia": "1", "MediaUrl0": "https://api.twilio.com/x/Media/ME1",
        "MediaContentType0": "audio/ogg",
    }
    sig = RequestValidator(TOKEN).compute_signature(URL, params)
    r = client.post("/webhook/whatsapp", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200
    assert calls == [("+15551230000", "", "https://api.twilio.com/x/Media/ME1", "audio/ogg")]


def test_weekly_nudge_requires_token(monkeypatch):
    monkeypatch.setattr(config, "NUDGE_TOKEN", "secret")
    client = TestClient(main.app)
    assert client.post("/tasks/weekly-nudge", params={"token": "wrong"}).status_code == 403
