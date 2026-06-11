"""WhatsApp channel adapter (Twilio).

Keeps the brain channel-agnostic: this module parses inbound webhooks, verifies the
Twilio signature, sends outbound messages, and builds the cross-partner relay text.

NOTE on the 24h rule: any bot-initiated message (the weekly nudge AND cross-partner
relays) must be a pre-approved WhatsApp **template** when the recipient is outside their
24h window. In the Twilio sandbox during dogfooding both partners are active, so free-form
sends work; production must switch these to templates.
"""
import httpx
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from app import config

_WHATSAPP_PREFIX = "whatsapp:"


def _client() -> Client:
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def strip_prefix(addr: str) -> str:
    """'whatsapp:+9199...' -> '+9199...'."""
    return (addr or "").replace(_WHATSAPP_PREFIX, "")


def verify_signature(url: str, params: dict, signature: str) -> bool:
    """Validate Twilio's X-Twilio-Signature over the public URL + posted params."""
    if not config.TWILIO_AUTH_TOKEN:
        return False
    return RequestValidator(config.TWILIO_AUTH_TOKEN).validate(url, params, signature or "")


def public_url(request_path: str, fallback: str) -> str:
    """The URL Twilio signed. Behind ngrok the internal request URL differs from the
    public one, so prefer PUBLIC_BASE_URL when set."""
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL.rstrip("/") + request_path
    return fallback


def send_message(to_phone: str, body: str) -> None:
    """Send a WhatsApp message to a bare phone number (e.g. '+9199...')."""
    _client().messages.create(
        from_=config.TWILIO_WHATSAPP_FROM,
        to=f"{_WHATSAPP_PREFIX}{to_phone}",
        body=body,
    )


def download_media(url: str):
    """Fetch Twilio media bytes (authenticated; follows the redirect to S3).
    Returns (bytes, content_type). Used for inbound voice notes."""
    r = httpx.get(
        url,
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
        follow_redirects=True,
        timeout=30.0,
    )
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "")


def build_relay(speaker_name, wrote) -> str:
    """A short note for the partner's thread when shared state changed. Returns "" when
    nothing worth relaying happened (e.g. only a name was saved)."""
    who = speaker_name or "Your partner"
    parts = []
    if "save_meal_plan" in wrote:
        parts.append(f"{who} planned this week's meals 🍽️")
    if "save_grocery_list" in wrote or "update_grocery_list" in wrote:
        parts.append(f"{who} updated the grocery list 🛒")
    if "log_spend" in wrote:
        parts.append(f"{who} logged a grocery spend 🧾")
    if "save_profile" in wrote:
        parts.append(f"{who} updated your household preferences ⚙️")
    return " ".join(parts)
