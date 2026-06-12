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

# Deployment env + the local test harness gate. /chat (which trusts a caller-supplied
# phone) must NOT be exposed in prod — it's a local testing convenience only.
HOUSY_ENV = os.environ.get("HOUSY_ENV", "dev")
ENABLE_TEST_CHAT = os.environ.get("ENABLE_TEST_CHAT", "false").lower() in ("1", "true", "yes")

# --- M4: storage backend + async processing ---------------------------------
# Storage: 'file' (local dev + unit tests) or 'firestore' (prod). Defaults to file so
# nothing changes until the Firestore backend is wired and selected.
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "file")

# Async: when true, the webhook enqueues to Cloud Tasks and a worker processes the
# message (durable + autoscaling). When false, processing runs inline/BackgroundTask
# (local dev). Defaults false.
USE_CLOUD_TASKS = os.environ.get("USE_CLOUD_TASKS", "false").lower() in ("1", "true", "yes")
TASKS_QUEUE = os.environ.get("TASKS_QUEUE", "housy-messages")
TASKS_LOCATION = os.environ.get("TASKS_LOCATION", "us-central1")
TASKS_WORKER_URL = os.environ.get("TASKS_WORKER_URL", "")        # https://<run-url>/tasks/process
TASKS_SERVICE_ACCOUNT = os.environ.get("TASKS_SERVICE_ACCOUNT", "")  # OIDC identity for the worker call

# Weak/placeholder nudge tokens we refuse in production.
_WEAK_TOKENS = {"", "change-me", "change-me-to-any-secret", "hello"}


def missing_prod_secrets() -> list:
    """Security-critical config that must be present before a public deploy."""
    missing = []
    if USE_VERTEX and not GCP_PROJECT:
        missing.append("GCP_PROJECT")
    if not TWILIO_AUTH_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    if NUDGE_TOKEN in _WEAK_TOKENS:
        missing.append("NUDGE_TOKEN (set a strong, non-default value)")
    return missing

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
