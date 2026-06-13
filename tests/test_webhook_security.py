import base64
import hashlib
import hmac

from webhook.security import verify_hmac

SECRET = "shh-secret"
BODY = b'{"id":123,"name":"#1001"}'


def sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_valid_signature_passes():
    assert verify_hmac(BODY, sign(BODY, SECRET), SECRET) is True


def test_tampered_body_fails():
    assert verify_hmac(BODY + b"x", sign(BODY, SECRET), SECRET) is False


def test_wrong_secret_fails():
    assert verify_hmac(BODY, sign(BODY, "other"), SECRET) is False


def test_empty_or_malformed_header_fails():
    assert verify_hmac(BODY, "", SECRET) is False
    assert verify_hmac(BODY, "not-base64-!!!", SECRET) is False


def test_empty_secret_fails():
    assert verify_hmac(BODY, sign(BODY, SECRET), "") is False
