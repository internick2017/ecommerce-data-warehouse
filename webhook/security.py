"""Shopify webhook HMAC verification (constant-time)."""
import base64
import hashlib
import hmac


def verify_hmac(raw_body: bytes, header_b64: str, secret: str) -> bool:
    """True iff base64(HMAC-SHA256(secret, raw_body)) matches the header, constant-time."""
    if not header_b64 or not secret:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    try:
        return hmac.compare_digest(expected, header_b64)
    except Exception:
        return False
