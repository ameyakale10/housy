"""Central config for Housy. Reads from environment (.env in dev)."""
import os
from dotenv import load_dotenv

load_dotenv()  # load .env if present

MODEL = os.environ.get("HOUSY_MODEL", "gemini-2.5-flash")

# --- Provider mode ---------------------------------------------------------
# Vertex AI (default): bills against your Google Cloud credits.
# Set USE_VERTEX=false to use an AI Studio API key instead (separate free quota).
USE_VERTEX = os.environ.get("USE_VERTEX", "true").lower() in ("1", "true", "yes")

# Vertex mode (auth via `gcloud auth application-default login` — no key in code):
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# AI Studio mode (only used when USE_VERTEX=false):
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Default household for the single-tenant MVP (both partners map here).
DEFAULT_HOUSEHOLD_ID = os.environ.get("DEFAULT_HOUSEHOLD_ID", "h1")

# --- WhatsApp / Twilio (M2) ------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
# Twilio WhatsApp sandbox sender by default.
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
# Public https base URL Twilio posts to (e.g. the ngrok URL) — needed so the
# signature is validated against the URL Twilio actually signed, not the internal one.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

# Weekly nudge: a shared secret protects the cron endpoint; the text is a stand-in
# (in production this MUST be a pre-approved WhatsApp template for the 24h-window rule).
NUDGE_TOKEN = os.environ.get("NUDGE_TOKEN", "")
NUDGE_TEXT = os.environ.get(
    "NUDGE_TEXT",
    "Hi! It's Housy 👋 Want to plan this week's meals and grocery list?",
)

# Repo root (one level up from this app/ folder). Used to find data files.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
