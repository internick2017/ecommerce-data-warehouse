# Phase 2 — Shopify Webhooks (event-driven ingestion) — Design Spec

**Date:** 2026-06-13
**Author:** Nick Granados (with Claude)
**Status:** Approved
**Builds on:** the MVP (`docs/superpowers/specs/2026-06-12-ecommerce-data-warehouse-design.md`), already on `master` with real AWS RDS + S3.

## Purpose

Add an **event-driven ingestion path** alongside the existing batch ELT pipeline: a FastAPI
receiver for Shopify `orders/create` / `orders/updated` webhooks that verifies the HMAC
signature, deduplicates, normalizes the webhook payload into the canonical record shape, and
lands it idempotently in `raw.orders` — the same raw layer the batch pipeline feeds.

This phase exists to demonstrate the JD's **"Webhooks & Event-Driven Pipelines (Strong):
webhook ingestion, payload validation, idempotency, signature verification, asynchronous
processing patterns"** — with real, tested code against the live store.

**Success criteria:** a signed webhook POST lands the order in `raw.orders` and records the
event in `meta.webhook_events`; an invalid HMAC is rejected with 401 and writes nothing; a
duplicate delivery is a no-op; the batch transforms then surface the order in the curated star
schema. Demonstrated end-to-end once against the real store via a cloudflared tunnel.

## Scope decisions (from brainstorming)

- **One sub-project.** Phases 3 (ODBC) and 4 (cloud-native) are separate specs, built later.
- **Processing model:** land raw fast (verify → dedupe → normalize → validate → upsert →
  record event → 200), transforms stay on the batch cadence. Ingestion is decoupled from
  transformation — the honest "asynchronous processing pattern" here, with no extra infra.
- **Exposure:** build + test locally; demo end-to-end with a temporary `cloudflared` tunnel and
  one real Shopify webhook registration. Permanent public exposure (Lambda URL) is deferred to
  Phase 4.
- **Reuse over duplication:** the normalizer maps the webhook JSON into the *same* canonical
  shape the GraphQL extractor produces, so `load.models.validate_record`,
  `load.pg_loader.upsert_raw`, and the existing staging/curated SQL all work unchanged.

## Architecture

A new `webhook/` package containing a FastAPI app. It shares the database and the existing
`load/` + `transform/` modules; it does not modify the batch path.

```
Shopify orders/create|updated  ->  POST /webhooks/shopify/orders
   |
   | 1. read raw body + headers (X-Shopify-Hmac-Sha256, X-Shopify-Webhook-Id, X-Shopify-Topic)
   v
 verify HMAC-SHA256(raw_body, secret)  --invalid-->  401, log, no write
   |
 dedupe by X-Shopify-Webhook-Id (meta.webhook_events)  --seen-->  200 no-op
   |
 normalize webhook JSON -> canonical record (GraphQL-node shape)
   |
 validate_record('orders', record)  --invalid-->  raw.rejects, return 200 (ack)
   |
 pg_loader.upsert_raw('orders', [record])  -> raw.orders  (idempotent by shopify_gid)
   |
 record event in meta.webhook_events (status=processed)
   |
   v
  200 (fast)

[ batch: python pipeline.py  ->  staging + curated pick up the new raw rows ]
```

## Components

Each file has one responsibility and is independently testable.

### `webhook/security.py`
- `verify_hmac(raw_body: bytes, header_b64: str, secret: str) -> bool`
- HMAC-SHA256 of the raw request body, base64-encoded, compared to the header with
  `hmac.compare_digest` (constant-time). Returns False on any mismatch or malformed header.

### `webhook/normalizer.py`
- `webhook_order_to_record(payload: dict) -> dict`
- Maps the Shopify **webhook** order JSON (REST shape) to the **canonical** record shape that
  `extract.extractor.extract_entity` yields and that `validate_record('orders', ...)` +
  `transform/sql/010_staging.sql` expect:
  - `id` ← `payload["admin_graphql_api_id"]` (the GID; falls back to building it from the
    numeric `id` if absent)
  - `name`, `currencyCode` ← `currency`
  - `createdAt`/`processedAt`/`updatedAt` ← `created_at`/`processed_at`/`updated_at`
  - `totalPriceSet.shopMoney.amount` ← `total_price`;
    `subtotalPriceSet.shopMoney.amount` ← `subtotal_price`
  - `customer` ← `{ "id": customer.admin_graphql_api_id }` or `None` for guest orders
  - `lineItems.edges[].node` ← each `line_items[]` mapped to
    `{ id, title, quantity, sku, product:{id}, originalUnitPriceSet:{shopMoney:{amount: price}} }`
- Pure function, fully unit-testable, no DB or network.

### `webhook/app.py`
- FastAPI app with `POST /webhooks/shopify/orders`.
- Dependencies injected (DB connection factory + webhook secret) so the app is testable with a
  Docker Postgres and a known secret.
- Handler order: read raw body → verify HMAC → dedupe → normalize → validate → upsert →
  record event → respond. Status codes per the error-handling table below.
- A `GET /healthz` returning `{"status":"ok"}` for liveness.

### `transform/sql/002_webhook_events.sql`
- `meta.webhook_events`:
  - `event_id text primary key` (the `X-Shopify-Webhook-Id`)
  - `topic text`, `shopify_gid text`, `hmac_valid boolean`, `status text`
    (check: `received | processed | rejected`), `received_at timestamptz default now()`
- Idempotent (`create table if not exists`). Runs as part of bootstrap (the pipeline already
  runs `001_schemas.sql`; the webhook app runs `001` + `002` on startup).

### `run_webhook.py`
- Entrypoint: `load_dotenv()`, build the DB connection + read `SHOPIFY_WEBHOOK_SECRET`, run the
  app with uvicorn on `127.0.0.1:8000`.

### `register_webhook.py`
- One-shot helper: registers a Shopify `orders/create` (and `orders/updated`) webhook via the
  Admin GraphQL `webhookSubscriptionCreate` mutation, pointing at a given public URL. Prints the
  created subscription id. Used once for the live demo.

## Configuration

Add to `.env` / `.env.example`:
- `SHOPIFY_WEBHOOK_SECRET=` — the signing secret. For the live demo, taken from the Shopify
  admin webhook (Settings → Notifications → Webhooks) or the custom app's API secret; documented
  in the demo runbook.

New dependencies in `requirements.txt`: `fastapi`, `uvicorn[standard]`, `httpx` (TestClient +
registration).

## Error handling

| Condition | Response | DB effect |
|---|---|---|
| Invalid / missing HMAC | 401 | none (anti-spoofing) |
| Duplicate `X-Shopify-Webhook-Id` | 200 | no-op (event row already present) |
| Malformed JSON / failed validation | 200 (ack) | `raw.rejects` row; `meta.webhook_events` status=rejected |
| Valid event | 200 | `raw.orders` upsert + `meta.webhook_events` status=processed |
| DB / unexpected error | 500 | Shopify retries later (transient) |

Returning 200 on permanently-bad payloads stops Shopify's retry storm; 500 is reserved for
transient failures we *want* retried. Double idempotency: `meta.webhook_events` PK on event_id
**and** `raw.orders` upsert keyed by `shopify_gid`.

## Testing

`tests/` (pytest), reusing the `db` fixture (Docker Postgres on 5433) and `tests/fixtures.py`.

- **`webhook/security.py`:** valid signature → True; tampered body → False; wrong secret →
  False; malformed/empty header → False.
- **`webhook/normalizer.py`:** a realistic Shopify webhook order JSON → correct canonical record
  (gid, name, amounts, line items flattened, sku/product gid); guest order (`customer: null`) →
  `customer` is None; multi-line order → all `lineItems.edges` present.
- **`webhook/app.py` (FastAPI TestClient + Postgres):**
  - signed valid webhook → 200, `raw.orders` has the row, `meta.webhook_events` status=processed.
  - invalid HMAC → 401, `raw.orders` empty, nothing recorded.
  - duplicate webhook-id → second call 200 no-op, still one raw row and one event row.
  - invalid payload (passes HMAC, fails validation) → 200, `raw.rejects` row, event=rejected.
  - end-to-end: after a webhook lands, running the transforms (`010` + `020`) surfaces the order
    in `curated.fact_orders`.

The signing helper for tests computes the same HMAC the receiver verifies (shared `security.py`),
so tests exercise the real verification path, not a bypass.

## Demo (manual, once)

1. `python run_webhook.py` (uvicorn on :8000).
2. `cloudflared tunnel --url http://localhost:8000` → public https URL.
3. Put `SHOPIFY_WEBHOOK_SECRET` in `.env`; `python register_webhook.py <tunnel-url>/webhooks/shopify/orders`.
4. Create/update a test order in Shopify (or `seed_shopify.py --count 1`) → webhook fires →
   confirm the row in `raw.orders` and `meta.webhook_events`. Capture the log.

## Deliverable updates

- README: add the event-driven path to the architecture diagram and a short "Phase 2 — Webhooks"
  section (signature verification, idempotency, normalization, async decoupling).
- The GitHub repo gains the `webhook/` package, new tests, and the SQL — another concrete,
  tested JD bullet.

## Out of scope (this phase)

- Permanent public hosting (Lambda Function URL) — Phase 4.
- Webhook topics beyond orders (products/customers) — same pattern, add later if useful.
- A real message queue (SQS/Redis) — the raw-landing + batch-transform split already provides
  the decoupling; a broker is Phase 4 territory.
