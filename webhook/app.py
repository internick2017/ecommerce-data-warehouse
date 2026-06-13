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
