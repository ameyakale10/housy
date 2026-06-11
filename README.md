# Housy

A household assistant for couples, reachable over WhatsApp. Housy remembers your
preferences, plans meals, builds grocery lists, and tracks store visits and bills.

This is the product service. The agent's data/memory model lives in
[`DATA-MODEL.md`](DATA-MODEL.md); its preferences in `couple-profile.md`.

## Stack
- **Python + FastAPI** — the service
- **Google Gemini via Vertex AI** (`google-genai`, Flash tier) — the brain, billed to
  Google Cloud credits
- File-based memory now (`data/`), a real database later

## Run it locally (Slice 1: talk to the brain)

1. Create a virtual env and install deps:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Set up Vertex AI access (one time):
   ```bash
   gcloud auth application-default login   # authenticate
   ```
   Then copy the env file and set your project id:
   ```bash
   cp .env.example .env
   # edit .env → set GCP_PROJECT to your Google Cloud project id
   ```
   (Make sure the Vertex AI API is enabled on that project.)
3. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```
4. Talk to Housy:
   ```bash
   curl -s localhost:8000/chat -H 'content-type: application/json' \
     -d '{"message":"hi Housy, can you help us plan meals?"}'
   ```

## Roadmap
- [x] M0 — JSON store + Pydantic models + atomic per-household lock
- [x] M1 — stateful tool-calling brain, identity guardrails, memory
- [x] M2 — WhatsApp loop (Twilio): webhook + signature verify + SID dedup +
  cross-partner relay + weekly-nudge endpoint *(code done; needs Twilio creds to go live)*
- [ ] M3 — dogfood for a real week over WhatsApp
- [ ] M4 — Firestore + Cloud Run
- [ ] M5 — receipt OCR + budgeting

## Going live on WhatsApp (M2)
1. Twilio account (free trial) → copy Account SID + Auth Token into `.env`.
2. Activate the WhatsApp Sandbox; join it from your phone (send the join code to the
   sandbox number).
3. Expose the local server: `ngrok http 8000`; put the https URL in `.env` as
   `PUBLIC_BASE_URL`.
4. In Twilio, set the sandbox "When a message comes in" webhook to
   `https://<ngrok>/webhook/whatsapp` (HTTP POST).
5. `uvicorn app.main:app --reload`, then message the sandbox number from WhatsApp.
