"""Cloud Tasks — durable async processing for inbound WhatsApp messages.

In production (USE_CLOUD_TASKS=true) the webhook ENQUEUES each message and returns
instantly; Cloud Tasks delivers it to the /tasks/process worker as an OIDC-authenticated
POST, with automatic retries. The webhook stays fast, the slow Gemini work runs as a
normal autoscaled request, and nothing is lost when Cloud Run recycles instances.

The google libraries are imported lazily so local dev + offline tests don't need them.
"""
import json

from app import config


def enqueue_message(payload: dict) -> None:
    """Drop one inbound message onto the queue, targeting the worker with an OIDC token."""
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(config.GCP_PROJECT, config.TASKS_LOCATION, config.TASKS_QUEUE)
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": config.TASKS_WORKER_URL,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode("utf-8"),
            "oidc_token": {
                "service_account_email": config.TASKS_SERVICE_ACCOUNT,
                "audience": config.TASKS_WORKER_URL,
            },
        }
    }
    client.create_task(parent=parent, task=task)


def verify_oidc(authorization_header: str) -> bool:
    """Verify the worker request is a Google-signed OIDC token from OUR service account,
    with the audience set to our worker URL. Rejects anything else."""
    if not authorization_header.startswith("Bearer "):
        return False
    token = authorization_header[len("Bearer "):]
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            token, g_requests.Request(), audience=config.TASKS_WORKER_URL
        )
    except Exception:  # noqa: BLE001 — any verification failure = reject
        return False
    if config.TASKS_SERVICE_ACCOUNT and claims.get("email") != config.TASKS_SERVICE_ACCOUNT:
        return False
    return bool(claims.get("email_verified", True))
