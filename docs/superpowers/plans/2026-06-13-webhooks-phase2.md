# Phase 2 — Shopify Webhooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI webhook receiver that verifies Shopify's HMAC signature, deduplicates by event id, normalizes the webhook order JSON into the canonical record shape, and lands it idempotently in `raw.orders` — reusing the existing `load/` and `transform/` modules so the batch staging/curated SQL works unchanged.

**Architecture:** A new self-contained `webhook/` package (security, normalizer, event store, FastAPI app) plus one new SQL file (`meta.webhook_events`) and two entrypoints. The receiver lands raw fast and returns 200; the existing `pipeline.py` batch transforms surface the order in the star schema on its normal cadence. Nothing in the batch path changes.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx (TestClient), pydantic v2 (reused), psycopg 3 (reused), pytest, Docker Postgres 16 (port 5433).

**Spec:** `docs/superpowers/specs/2026-06-13-webhooks-phase2-design.md`

**Environment notes for the implementer:**
- Windows 10, PowerShell. Python: `.venv\Scripts\python.exe`. Tests: `.venv\Scripts\python.exe -m pytest`.
- Repo root: `e:\dev\08-data\ecommerce-data-warehouse`. Paths below are relative to it.
- Docker Postgres must be up: `docker compose up -d` (port 5433, `DATABASE_URL=postgresql://dw:dw@localhost:5433/ecommerce_dw`).
- Reused, already-built modules (do not modify their behavior):
  - `load.models.validate_record(entity, record) -> (ok: bool, reason: str|None)`
  - `load.pg_loader.upsert_raw(conn, entity, records, load_id, extracted_at)` — idempotent upsert by `shopify_gid`; wraps its own `conn.transaction()`.
  - `load.pg_loader.insert_reject(conn, entity, payload, reason, load_id)`
  - `transform.runner.run_sql_files(conn, paths)` — runs `.sql` split on `;`.
  - `transform/sql/001_schemas.sql` creates the `raw/staging/curated/meta` schemas and `raw.orders`, `raw.rejects`, etc.
- The webhook origin uses `load_id = 0` (sentinel; `raw.orders.load_id` is `bigint not null` with no FK, so 0 is valid and means "webhook, not a batch load").

---

### Task 1: Dependencies + `meta.webhook_events` SQL

**Files:**
- Modify: `requirements.txt`
- Create: `transform/sql/002_webhook_events.sql`
- Create: `webhook/__init__.py` (empty)
- Test: `tests/test_webhook_events_sql.py`

- [ ] **Step 1: Add dependencies to `requirements.txt`**

Append these three lines:

```
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
```

- [ ] **Step 2: Install them**

Run: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: fastapi, uvicorn, httpx install cleanly.

- [ ] **Step 3: Create empty `webhook/__init__.py`**

Create `webhook/__init__.py` — empty file.

- [ ] **Step 4: Write the failing test**

`tests/test_webhook_events_sql.py`:

```python
from transform.runner import run_sql_files

SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def test_webhook_events_table_created(db):
    run_sql_files(db, SQL)
    cols = {
        r[0]
        for r in db.execute(
            "select column_name from information_schema.columns "
            "where table_schema='meta' and table_name='webhook_events'"
        ).fetchall()
    }
    assert {"event_id", "topic", "shopify_gid", "hmac_valid", "status", "received_at"} <= cols


def test_webhook_events_status_check_and_idempotent(db):
    run_sql_files(db, SQL)
    run_sql_files(db, SQL)  # idempotent re-run must not raise
    # primary key on event_id: a second insert of the same id is a no-op via ON CONFLICT
    db.execute(
        "insert into meta.webhook_events (event_id, status) values ('e1', 'received')"
    )
    db.execute(
        "insert into meta.webhook_events (event_id, status) values ('e1', 'processed') "
        "on conflict (event_id) do nothing"
    )
    rows = db.execute(
        "select status from meta.webhook_events where event_id='e1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 'received'
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_events_sql.py -v`
Expected: FAIL — `002_webhook_events.sql` not found.

- [ ] **Step 6: Create `transform/sql/002_webhook_events.sql`**

(`meta` schema is created by `001`. One statement per `;`, no semicolons in literals.)

```sql
create table if not exists meta.webhook_events (
    event_id    text primary key,
    topic       text,
    shopify_gid text,
    hmac_valid  boolean,
    status      text not null default 'received' check (status in ('received','processed','rejected')),
    received_at timestamptz not null default now()
);
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_events_sql.py -v`
Expected: 2 PASSED.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt transform/sql/002_webhook_events.sql webhook/__init__.py tests/test_webhook_events_sql.py
git commit -m "feat(webhook): meta.webhook_events table + FastAPI deps"
```

---

### Task 2: HMAC signature verification

**Files:**
- Create: `webhook/security.py`
- Test: `tests/test_webhook_security.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_webhook_security.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webhook.security'`.

- [ ] **Step 3: Create `webhook/security.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_security.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webhook/security.py tests/test_webhook_security.py
git commit -m "feat(webhook): constant-time HMAC verification"
```

---

### Task 3: Webhook payload normalizer

**Files:**
- Create: `webhook/normalizer.py`
- Test: `tests/test_webhook_normalizer.py`

**Context:** Shopify's webhook order JSON (REST shape) differs from the GraphQL extract shape.
This maps it to the canonical shape `validate_record('orders', ...)` and `010_staging.sql`
expect, so the rest of the pipeline is unchanged. Webhook fields used: `id` (int),
`admin_graphql_api_id` (GID), `name`, `created_at`/`processed_at`/`updated_at`, `currency`,
`total_price`, `subtotal_price`, `customer.{id, admin_graphql_api_id}`, and
`line_items[].{id, admin_graphql_api_id, title, quantity, sku, price, product_id}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_webhook_normalizer.py`:

```python
from webhook.normalizer import webhook_order_to_record

WEBHOOK_ORDER = {
    "id": 820982911946154500,
    "admin_graphql_api_id": "gid://shopify/Order/820982911946154508",
    "name": "#1001",
    "created_at": "2026-06-01T10:00:00-04:00",
    "processed_at": "2026-06-01T10:00:00-04:00",
    "updated_at": "2026-06-01T10:05:00-04:00",
    "currency": "EUR",
    "total_price": "49.90",
    "subtotal_price": "41.24",
    "customer": {
        "id": 115310627314723950,
        "admin_graphql_api_id": "gid://shopify/Customer/115310627314723954",
    },
    "line_items": [
        {
            "id": 866550311766439000,
            "admin_graphql_api_id": "gid://shopify/LineItem/866550311766439020",
            "title": "Mug",
            "quantity": 2,
            "sku": "SKU-1",
            "price": "15.00",
            "product_id": 632910392,
        }
    ],
}


def test_maps_order_top_level_fields():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    assert rec["id"] == "gid://shopify/Order/820982911946154508"
    assert rec["name"] == "#1001"
    assert rec["currencyCode"] == "EUR"
    assert rec["totalPriceSet"]["shopMoney"]["amount"] == "49.90"
    assert rec["subtotalPriceSet"]["shopMoney"]["amount"] == "41.24"
    assert rec["processedAt"] == "2026-06-01T10:00:00-04:00"


def test_maps_customer_gid():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    assert rec["customer"] == {"id": "gid://shopify/Customer/115310627314723954"}


def test_guest_order_has_null_customer():
    guest = dict(WEBHOOK_ORDER, customer=None)
    rec = webhook_order_to_record(guest)
    assert rec["customer"] is None


def test_maps_line_items_to_edges():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    edges = rec["lineItems"]["edges"]
    assert len(edges) == 1
    node = edges[0]["node"]
    assert node["id"] == "gid://shopify/LineItem/866550311766439020"
    assert node["quantity"] == 2
    assert node["sku"] == "SKU-1"
    assert node["product"]["id"] == "gid://shopify/Product/632910392"
    assert node["originalUnitPriceSet"]["shopMoney"]["amount"] == "15.00"


def test_builds_gid_when_admin_graphql_api_id_absent():
    minimal = dict(WEBHOOK_ORDER)
    minimal = {k: v for k, v in minimal.items() if k != "admin_graphql_api_id"}
    rec = webhook_order_to_record(minimal)
    assert rec["id"] == "gid://shopify/Order/820982911946154500"


def test_normalized_record_passes_validation():
    from load.models import validate_record
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    ok, reason = validate_record("orders", rec)
    assert ok is True, reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_normalizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webhook.normalizer'`.

- [ ] **Step 3: Create `webhook/normalizer.py`**

```python
"""Map a Shopify webhook order payload (REST shape) to the canonical record shape.

The canonical shape matches what extract.extractor yields and what
load.models.OrderRecord + transform/sql/010_staging.sql consume, so the rest of
the pipeline handles webhook-sourced orders identically to API-extracted ones.
"""


def _gid(kind, numeric_id):
    return f"gid://shopify/{kind}/{numeric_id}"


def _money(amount):
    return {"shopMoney": {"amount": amount}}


def _line_item_node(item):
    li_gid = item.get("admin_graphql_api_id") or _gid("LineItem", item.get("id"))
    product = None
    if item.get("product_id") is not None:
        product = {"id": _gid("Product", item["product_id"])}
    return {
        "id": li_gid,
        "title": item.get("title"),
        "quantity": item.get("quantity"),
        "sku": item.get("sku"),
        "product": product,
        "originalUnitPriceSet": _money(item.get("price")),
    }


def webhook_order_to_record(payload):
    order_gid = payload.get("admin_graphql_api_id") or _gid("Order", payload.get("id"))

    customer = payload.get("customer")
    if customer:
        customer_gid = customer.get("admin_graphql_api_id") or _gid("Customer", customer.get("id"))
        customer_ref = {"id": customer_gid}
    else:
        customer_ref = None

    edges = [{"node": _line_item_node(li)} for li in payload.get("line_items", [])]

    return {
        "id": order_gid,
        "name": payload.get("name"),
        "createdAt": payload.get("created_at"),
        "processedAt": payload.get("processed_at"),
        "updatedAt": payload.get("updated_at"),
        "currencyCode": payload.get("currency"),
        "totalPriceSet": _money(payload.get("total_price")),
        "subtotalPriceSet": _money(payload.get("subtotal_price")),
        "customer": customer_ref,
        "lineItems": {"edges": edges},
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_normalizer.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webhook/normalizer.py tests/test_webhook_normalizer.py
git commit -m "feat(webhook): normalize webhook order JSON to canonical record shape"
```

---

### Task 4: Event store (dedupe + record)

**Files:**
- Create: `webhook/events.py`
- Test: `tests/test_webhook_store.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_webhook_store.py`:

```python
from transform.runner import run_sql_files
from webhook import events

SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def bootstrap(db):
    run_sql_files(db, SQL)


def test_event_seen_roundtrip(db):
    bootstrap(db)
    assert events.event_seen(db, "evt-1") is False
    events.record_event(db, "evt-1", "orders/create", "gid://shopify/Order/1", True, "processed")
    assert events.event_seen(db, "evt-1") is True


def test_record_event_is_idempotent(db):
    bootstrap(db)
    events.record_event(db, "evt-1", "orders/create", "gid://1", True, "processed")
    events.record_event(db, "evt-1", "orders/create", "gid://1", True, "rejected")  # no-op
    rows = db.execute(
        "select status from meta.webhook_events where event_id='evt-1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "processed"  # first write wins


def test_record_event_persists_fields(db):
    bootstrap(db)
    events.record_event(db, "evt-2", "orders/updated", "gid://shopify/Order/9", True, "processed")
    row = db.execute(
        "select topic, shopify_gid, hmac_valid, status from meta.webhook_events where event_id='evt-2'"
    ).fetchone()
    assert row == ("orders/updated", "gid://shopify/Order/9", True, "processed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webhook.events'`.

- [ ] **Step 3: Create `webhook/events.py`**

```python
"""meta.webhook_events store: dedupe lookups + idempotent event recording."""


def event_seen(conn, event_id):
    """True if this Shopify webhook id was already recorded."""
    row = conn.execute(
        "select 1 from meta.webhook_events where event_id = %s", (event_id,)
    ).fetchone()
    return row is not None


def record_event(conn, event_id, topic, shopify_gid, hmac_valid, status):
    """Insert the event row. Idempotent: a repeated event_id is a no-op (first write wins)."""
    conn.execute(
        """
        insert into meta.webhook_events (event_id, topic, shopify_gid, hmac_valid, status)
        values (%s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (event_id, topic, shopify_gid, hmac_valid, status),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_store.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add webhook/events.py tests/test_webhook_store.py
git commit -m "feat(webhook): event store with dedupe + idempotent recording"
```

---

### Task 5: FastAPI receiver app

**Files:**
- Create: `webhook/app.py`
- Test: `tests/test_webhook_app.py`

**Context:** `create_app(conn_factory, secret)` builds the FastAPI app with its dependencies
injected so tests use the Docker Postgres `db` fixture and a known secret. `conn_factory()`
returns a psycopg connection; in tests it returns the fixture connection.

- [ ] **Step 1: Write the failing tests**

`tests/test_webhook_app.py`:

```python
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
    gid = db.execute(
        "select shopify_gid from raw.orders"
    ).fetchone()[0]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webhook.app'`.

- [ ] **Step 3: Create `webhook/app.py`**

```python
"""FastAPI receiver for Shopify order webhooks.

Flow: verify HMAC -> dedupe by webhook id -> normalize -> validate -> upsert raw
-> record event -> 200. Returns 401 on bad signatures, 200 (ack) on permanently
bad payloads, 500 on transient DB errors (so Shopify retries).
"""
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response

from load import pg_loader
from load.models import validate_record
from webhook import events
from webhook.normalizer import webhook_order_to_record
from webhook.security import verify_hmac

WEBHOOK_LOAD_ID = 0  # sentinel: raw row originated from a webhook, not a batch load


def create_app(conn_factory, secret):
    app = FastAPI(title="ecommerce-dw webhooks")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/webhooks/shopify/orders")
    async def shopify_orders(request: Request):
        raw = await request.body()
        if not verify_hmac(raw, request.headers.get("X-Shopify-Hmac-Sha256", ""), secret):
            return Response(status_code=401)

        event_id = request.headers.get("X-Shopify-Webhook-Id", "")
        topic = request.headers.get("X-Shopify-Topic", "")
        conn = conn_factory()

        if event_id and events.event_seen(conn, event_id):
            return Response(status_code=200)  # duplicate delivery

        try:
            record = webhook_order_to_record(json.loads(raw))
        except Exception as exc:  # malformed JSON / unexpected shape
            pg_loader.insert_reject(
                conn, "orders", {"raw": raw.decode("utf-8", "replace")},
                f"parse: {exc}", WEBHOOK_LOAD_ID,
            )
            events.record_event(conn, event_id or "unknown", topic, None, True, "rejected")
            return Response(status_code=200)

        ok, reason = validate_record("orders", record)
        if not ok:
            pg_loader.insert_reject(conn, "orders", record, reason, WEBHOOK_LOAD_ID)
            events.record_event(conn, event_id or "unknown", topic, record.get("id"), True, "rejected")
            return Response(status_code=200)

        pg_loader.upsert_raw(
            conn, "orders", [record], load_id=WEBHOOK_LOAD_ID,
            extracted_at=datetime.now(timezone.utc),
        )
        events.record_event(conn, event_id or "unknown", topic, record["id"], True, "processed")
        return Response(status_code=200)

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_webhook_app.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: ALL PASSED (48 prior + 22 new ≈ 70).

- [ ] **Step 6: Commit**

```bash
git add webhook/app.py tests/test_webhook_app.py
git commit -m "feat(webhook): FastAPI receiver (HMAC, dedupe, normalize, validate, upsert)"
```

---

### Task 6: Entrypoints + config

**Files:**
- Create: `run_webhook.py`
- Create: `register_webhook.py`
- Modify: `.env.example`
- Test: `tests/test_register_webhook.py`

- [ ] **Step 1: Write the failing test (pure mutation-vars builder)**

`tests/test_register_webhook.py`:

```python
from register_webhook import build_subscription_vars


def test_build_subscription_vars():
    vars_ = build_subscription_vars("https://x.example/webhooks/shopify/orders", "ORDERS_CREATE")
    assert vars_["topic"] == "ORDERS_CREATE"
    assert vars_["sub"]["callbackUrl"] == "https://x.example/webhooks/shopify/orders"
    assert vars_["sub"]["format"] == "JSON"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_register_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'register_webhook'`.

- [ ] **Step 3: Create `register_webhook.py`**

```python
"""Register a Shopify order webhook pointing at a public callback URL (one-shot, live).

Usage: python register_webhook.py https://<tunnel>/webhooks/shopify/orders
Registers ORDERS_CREATE and ORDERS_UPDATED via the Admin GraphQL API.
"""
import sys

from dotenv import load_dotenv

MUTATION = """
mutation Create($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id }
    userErrors { field message }
  }
}
"""


def build_subscription_vars(callback_url, topic):
    return {"topic": topic, "sub": {"callbackUrl": callback_url, "format": "JSON"}}


def main():
    import os

    from extract.shopify_client import ShopifyClient

    if len(sys.argv) < 2:
        raise SystemExit("usage: python register_webhook.py <public-callback-url>")
    callback_url = sys.argv[1]

    load_dotenv()
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    for topic in ("ORDERS_CREATE", "ORDERS_UPDATED"):
        data = client.execute(MUTATION, build_subscription_vars(callback_url, topic))
        result = data["webhookSubscriptionCreate"]
        if result["userErrors"]:
            print(f"{topic}: FAILED -> {result['userErrors']}")
        else:
            print(f"{topic}: registered {result['webhookSubscription']['id']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_register_webhook.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Create `run_webhook.py`**

```python
"""Run the webhook receiver locally (uvicorn on 127.0.0.1:8000).

Bootstraps the schema, opens one DB connection, and serves create_app().
Expose publicly for a live demo with:  cloudflared tunnel --url http://localhost:8000
"""
import os

import uvicorn
from dotenv import load_dotenv

from load import pg_loader
from transform.runner import run_sql_files
from webhook.app import create_app

BOOTSTRAP_SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def build():
    load_dotenv()
    conn = pg_loader.connect()
    run_sql_files(conn, BOOTSTRAP_SQL)
    secret = os.environ["SHOPIFY_WEBHOOK_SECRET"]
    return create_app(conn_factory=lambda: conn, secret=secret)


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=8000)
```

- [ ] **Step 6: Update `.env.example`**

Append after the Shopify section:

```ini

# Shopify webhook signing secret (Settings -> Notifications -> Webhooks, or the
# custom app's API secret). Required by run_webhook.py.
SHOPIFY_WEBHOOK_SECRET=
```

- [ ] **Step 7: Commit**

```bash
git add run_webhook.py register_webhook.py .env.example tests/test_register_webhook.py
git commit -m "feat(webhook): uvicorn entrypoint + Shopify webhook registration helper"
```

---

### Task 7: Live demo + README

No new app code; wires the receiver to the real store and documents the phase.

- [ ] **Step 1 (manual, Nick): run + expose + register**

```powershell
# terminal 1
.venv\Scripts\python.exe run_webhook.py            # needs SHOPIFY_WEBHOOK_SECRET in .env
# terminal 2
cloudflared tunnel --url http://localhost:8000     # copy the https URL it prints
# terminal 3
.venv\Scripts\python.exe register_webhook.py https://<tunnel>/webhooks/shopify/orders
```

If `cloudflared` is not installed: `winget install --id Cloudflare.cloudflared` (or download the
binary). The `SHOPIFY_WEBHOOK_SECRET` must match what Shopify signs with — for an Admin-API
created subscription on a custom app, that is the app's API secret key (Shopify admin → Apps →
storeia → API credentials).

- [ ] **Step 2 (manual, Nick): fire a webhook**

Create or update a test order: `.venv\Scripts\python.exe seed_shopify.py --count 1 --seed 99`
(or edit any order in the Shopify admin). Watch terminal 1 log a 200, then verify:

```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from load import pg_loader; c=pg_loader.connect(); print('events:', c.execute('select event_id, topic, status from meta.webhook_events order by received_at desc limit 3').fetchall())"
```

Expected: a `processed` event row for the order. Capture the receiver log for the README.

- [ ] **Step 3: Update `README.md`**

Add the event-driven path to the architecture mermaid diagram (a branch from "Shopify" into a
"Webhook receiver (FastAPI)" box feeding `raw.orders`), and add this section after "Design
decisions":

```markdown
## Phase 2 — Event-driven ingestion (webhooks)

A FastAPI receiver (`webhook/`) ingests Shopify `orders/create` / `orders/updated` webhooks in
real time, alongside the batch pipeline:

- **Signature verification** — HMAC-SHA256 of the raw body, constant-time compared (`webhook/security.py`).
- **Idempotency** — deduplicated by `X-Shopify-Webhook-Id` in `meta.webhook_events`, and the
  `raw.orders` upsert is keyed by Shopify GID, so redelivered events are no-ops.
- **Normalization** — the webhook JSON (REST shape) is mapped to the same canonical record the
  GraphQL extractor produces (`webhook/normalizer.py`), so staging/curated SQL is unchanged.
- **Async decoupling** — the receiver lands raw and returns 200 in milliseconds; the star-schema
  transforms run on the batch cadence. Bad payloads are acked (200) and routed to `raw.rejects`;
  only transient failures return 500 for Shopify to retry.

Run locally with `python run_webhook.py` and expose via a cloudflared tunnel; `register_webhook.py`
subscribes the store to the tunnel URL.
```

- [ ] **Step 4: Final test sweep + commit**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: ALL PASSED.

```bash
git add README.md
git commit -m "docs: document Phase 2 event-driven webhook ingestion"
```

---

## Self-review notes

- **Spec coverage:** security.py (Task 2), normalizer.py (Task 3), app.py (Task 5),
  `meta.webhook_events` SQL (Task 1), run_webhook.py + register_webhook.py + config (Task 6),
  error-handling table (Task 5 tests cover 401 / 200-ack / dedupe / processed; 500 is the
  FastAPI default on unhandled exception), testing matrix (Tasks 2–5), demo + README (Task 7).
  The spec's `webhook/events.py` is introduced as Task 4 (the dedupe/record helper the spec
  folds under app.py — split out for a clean, testable unit).
- **load_id sentinel:** `WEBHOOK_LOAD_ID = 0` is used consistently in Task 5.
- **Reuse:** `validate_record`, `pg_loader.upsert_raw`, `pg_loader.insert_reject`,
  `transform.runner.run_sql_files` are called with their real signatures; no batch code changes.

## Execution order & estimate

- Tasks 1–6 are codeable + testable locally in one sitting (~1.5–2h with reviews).
- Task 7 has manual steps (cloudflared + real Shopify webhook) for Nick; the README can be
  written from the design even before the live capture.

## Out of scope (per spec)

Lambda Function URL hosting (Phase 4), non-order webhook topics, external message queue.
