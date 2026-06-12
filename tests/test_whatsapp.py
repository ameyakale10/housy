"""M2 WhatsApp tests — signature gate, SID dedup, relay text, partner lookup."""
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import app.config as config
import app.identity as identity
import app.main as main
import app.store as store
from app import taskqueue
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


def test_webhook_schedules_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "USE_CLOUD_TASKS", False)
    calls = []
    monkeypatch.setattr(main, "_process_whatsapp", lambda *a: calls.append(a))
    client = TestClient(main.app)
    params = _form()
    sig = RequestValidator(TOKEN).compute_signature(URL, params)
    r = client.post("/webhook/whatsapp", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200
    assert calls == [("+15551230000", "hi", None, None, "SM123")]  # phone, body, media, type, sid


def test_process_whatsapp_dedups_sid(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    handled = []
    monkeypatch.setattr(main, "_handle_inbound", lambda *a: handled.append(a))
    main._process_whatsapp("+1", "hi", None, None, "SMX")
    main._process_whatsapp("+1", "hi", None, None, "SMX")  # duplicate SID
    assert len(handled) == 1  # processed exactly once


def test_webhook_enqueues_when_cloud_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(config, "USE_CLOUD_TASKS", True)
    enq, proc = [], []
    monkeypatch.setattr(taskqueue, "enqueue_message", lambda payload: enq.append(payload))
    monkeypatch.setattr(main, "_process_whatsapp", lambda *a: proc.append(a))
    client = TestClient(main.app)
    params = _form()
    sig = RequestValidator(TOKEN).compute_signature(URL, params)
    r = client.post("/webhook/whatsapp", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200
    assert enq and enq[0]["sid"] == "SM123" and enq[0]["from_phone"] == "+15551230000"
    assert proc == []  # queued, not processed inline


def test_worker_requires_oidc(monkeypatch):
    monkeypatch.setattr(taskqueue, "verify_oidc", lambda h: False)
    client = TestClient(main.app)
    assert client.post("/tasks/process", json={"from_phone": "+1", "body": "hi"}).status_code == 403


def test_worker_processes_with_valid_oidc(monkeypatch):
    monkeypatch.setattr(taskqueue, "verify_oidc", lambda h: True)
    got = []
    monkeypatch.setattr(main, "_process_whatsapp", lambda *a, **k: got.append((a, k)))
    client = TestClient(main.app)
    r = client.post("/tasks/process", json={
        "from_phone": "+1", "body": "hi", "media_url": None, "media_type": None, "sid": "S1"})
    assert r.status_code == 200
    assert got == [(("+1", "hi", None, None, "S1"), {"raise_on_error": True})]


def test_release_sid_allows_reprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    assert store.claim_sid("SMr") is True
    assert store.claim_sid("SMr") is False          # already claimed
    store.release_sid("SMr")
    assert store.claim_sid("SMr") is True            # reclaimable after release


def test_worker_retries_on_failure(tmp_path, monkeypatch):
    """A failed turn must return 500 (so Cloud Tasks retries) AND release the SID, so the
    retry re-processes instead of being deduped away as 'already handled'."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(taskqueue, "verify_oidc", lambda h: True)

    def boom(*a):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "_handle_inbound", boom)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/tasks/process", json={"from_phone": "+1", "body": "hi", "sid": "SMfail"})
    assert r.status_code == 500                       # signals Cloud Tasks to retry
    assert store.claim_sid("SMfail") is True          # SID released -> reprocessable


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
    assert calls == [("+15551230000", "", "https://api.twilio.com/x/Media/ME1", "audio/ogg", "SMvoice")]


def test_weekly_nudge_requires_token(monkeypatch):
    monkeypatch.setattr(config, "NUDGE_TOKEN", "secret")
    client = TestClient(main.app)
    # wrong token in the header is rejected; a token in the URL is ignored (header-only now)
    assert client.post("/tasks/weekly-nudge", headers={"X-Nudge-Token": "wrong"}).status_code == 403
    assert client.post("/tasks/weekly-nudge", params={"token": "secret"}).status_code == 403


def test_weekly_nudge_fans_out_to_all_phones(tmp_path, monkeypatch):
    import app.identity as identity
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "NUDGE_TOKEN", "secret")
    h = identity.resolve_or_create_household("+111")
    identity.link_phone("+222", h)  # both partners
    sent = []
    monkeypatch.setattr(whatsapp, "send_message", lambda to, body: sent.append(to))
    client = TestClient(main.app)
    r = client.post("/tasks/weekly-nudge", headers={"X-Nudge-Token": "secret"})
    assert r.status_code == 200 and r.json()["sent"] == 2
    assert set(sent) == {"+111", "+222"}
