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

# Repo root (one level up from this app/ folder). Used to find data files.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
