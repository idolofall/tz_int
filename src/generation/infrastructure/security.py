import hashlib
import hmac

from generation.domain.exceptions import InvalidSignatureError


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return digest


def verify_signature(secret: str, body: bytes, provided: str | None) -> None:
    if not provided:
        raise InvalidSignatureError("missing X-Signature")
    expected = compute_signature(secret, body)
    if not hmac.compare_digest(expected, provided):
        raise InvalidSignatureError("invalid X-Signature")
