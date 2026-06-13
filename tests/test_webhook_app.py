import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from transform.runner import run_sql_files
from webhook.app import create_app

SECRET = "test-secret"
SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]

ORDER = {
    "id": 5001,
    "admin_graphql_api_id": "gid://shopify/Order/5001",
    "name": "#5001",
    "created_at": "2026-06-10T12:00:00-04:00",
    "processed_at": "2026-06-10T12:00:00-04:00",
    "updated_at": "2026-06-10T12:00:00-04:00",
    "currency": "EUR",
    "total_price": "30.00",
    "subtotal_price": "30.00",
    "customer": {"id": 1, "admin_graphql_api_id": "gid://shopify/Customer/1"},
    "line_items": [
        {"id": 9001, "admin_graphql_api_id": "gid://shopify/LineItem/9001",
         "title": "Mug", "quantity": 2, "sku": "SKU-1", "price": "15.00", "product_id": 7001},
    ],
}


def sign(body: bytes) -> str:
    return base64.b64encode(
        hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()


def client(db):
    run_sql_files(db, SQL)
    app = create_app(conn_factory=lambda: db, secret=SECRET)
    return TestClient(app)


def post(c, body_dict, event_id="evt-1", hmac_header=None, topic="orders/create"):
    raw = json.dumps(body_dict).encode("utf-8")
    headers = {
        "X-Shopify-Hmac-Sha256": hmac_header if hmac_header is not None else sign(raw),
        "X-Shopify-Webhook-Id": event_id,
        "X-Shopify-Topic": topic,
        "Content-Type": "application/json",
    }
    return c.post("/webhooks/shopify/orders", content=raw, headers=headers)


def test_healthz(db):
    c = client(db)
    assert c.get("/healthz").json() == {"status": "ok"}


def test_valid_webhook_lands_order_and_records_event(db):
    c = client(db)
    resp = post(c, ORDER)
    assert resp.status_code == 200
    assert db.execute("select count(*) from raw.orders").fetchone()[0] == 1
    gid = db.execute("select shopify_gid from raw.orders").fetchone()[0]
    assert gid == "gid://shopify/Order/5001"
    ev = db.execute(
        "select status, hmac_valid from meta.webhook_events where event_id='evt-1'"
    ).fetchone()
    assert ev == ("processed", True)


def test_invalid_hmac_rejected_writes_nothing(db):
    c = client(db)
    resp = post(c, ORDER, hmac_header="wrong")
    assert resp.status_code == 401
    assert db.execute("select count(*) from raw.orders").fetchone()[0] == 0
    assert db.execute("select count(*) from meta.webhook_events").fetchone()[0] == 0


def test_duplicate_event_is_noop(db):
    c = client(db)
    assert post(c, ORDER, event_id="dup").status_code == 200
    assert post(c, ORDER, event_id="dup").status_code == 200
    assert db.execute("select count(*) from raw.orders").fetchone()[0] == 1
    assert db.execute(
        "select count(*) from meta.webhook_events where event_id='dup'"
    ).fetchone()[0] == 1


def test_invalid_payload_goes_to_rejects_and_acks(db):
    c = client(db)
    bad = {"id": 7, "admin_graphql_api_id": "gid://shopify/Order/7"}  # missing required fields
    resp = post(c, bad, event_id="bad-1")
    assert resp.status_code == 200
    assert db.execute("select count(*) from raw.rejects").fetchone()[0] == 1
    status = db.execute(
        "select status from meta.webhook_events where event_id='bad-1'"
    ).fetchone()[0]
    assert status == "rejected"


def test_landed_order_flows_to_curated_after_transforms(db):
    c = client(db)
    post(c, ORDER)
    run_sql_files(db, ["transform/sql/010_staging.sql", "transform/sql/020_curated.sql"])
    assert db.execute(
        "select count(*) from curated.fact_orders where order_gid='gid://shopify/Order/5001'"
    ).fetchone()[0] == 1
