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
- [x] Slice 0 — data model + meal-planning logic
- [x] Slice 1 — brain over HTTP (this)
- [ ] Slice 2 — WhatsApp channel (Twilio) → same brain
- [ ] Slice 3 — Housy writes plans/lists/bills into the data model
- [ ] Slice 4 — persistent DB + hosting
