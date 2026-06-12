import pytest
import requests
from extract.shopify_client import ShopifyClient, ShopifyError


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def make_client(responses, max_retries=3):
    session = FakeSession(responses)
    client = ShopifyClient(
        shop_domain="test.myshopify.com",
        access_token="tok123",
        session=session,
        max_retries=max_retries,
        sleep=lambda s: None,
    )
    return client, session


def test_execute_returns_data_and_sends_auth_header():
    ok = FakeResponse(200, {"data": {"shop": {"name": "x"}}})
    client, session = make_client([ok])
    data = client.execute("query { shop { name } }")
    assert data == {"shop": {"name": "x"}}
    call = session.calls[0]
    assert call["headers"]["X-Shopify-Access-Token"] == "tok123"
    assert "2025-01/graphql.json" in call["url"]


def test_retries_on_429_then_succeeds():
    ok = FakeResponse(200, {"data": {"ok": True}})
    client, session = make_client([FakeResponse(429), ok])
    assert client.execute("q") == {"ok": True}
    assert len(session.calls) == 2


def test_retries_on_throttled_graphql_error():
    throttled = FakeResponse(200, {"errors": [{"message": "Throttled",
                                               "extensions": {"code": "THROTTLED"}}]})
    ok = FakeResponse(200, {"data": {"ok": True}})
    client, session = make_client([throttled, ok])
    assert client.execute("q") == {"ok": True}
    assert len(session.calls) == 2


def test_gives_up_after_max_retries():
    client, _ = make_client([FakeResponse(429)] * 4, max_retries=3)
    with pytest.raises(ShopifyError):
        client.execute("q")


def test_non_throttle_graphql_error_raises():
    bad = FakeResponse(200, {"errors": [{"message": "syntax error"}]})
    client, _ = make_client([bad])
    with pytest.raises(ShopifyError, match="syntax error"):
        client.execute("q")
