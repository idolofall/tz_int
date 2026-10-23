import hashlib
import hmac
import json
from typing import Any

WEBHOOK_SECRET = "dev-webhook-secret"


def sign(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Signature": signature,
    }
