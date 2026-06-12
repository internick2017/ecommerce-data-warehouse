# E-commerce Data Warehouse — Design Spec

**Date:** 2026-06-12
**Author:** Nick Granados (with Claude)
**Status:** Approved

## Purpose

A real, end-to-end data integration case for the portfolio (nickgranados.com / github.com/internick2017), built against a live Shopify store (storeup.store). It exists to:

1. Close the specific skill gaps from two active interview processes:
   - **Genius Lab — Data Integration Developer:** AWS (RDS/S3/Lambda), ETL/ELT with incremental loads, webhooks (HMAC + idempotency), ODBC/legacy extraction, analytical SQL (CTEs, window functions), star schema, Power BI.
   - **Niuro — WordPress Engineer:** AWS RDS hands-on, CI/CD.
2. Produce a demonstrable portfolio piece: public repo + architecture diagram + live dashboard screenshots + short case study.

**Success criteria (MVP, days 1–3):** the pipeline runs end-to-end against real AWS — Shopify GraphQL → S3 → RDS Postgres (raw/staging/curated) → star schema → one Power BI dashboard — and is idempotent (re-running produces no duplicates). Nick can narrate every stage in interview language.

## Scope decisions (made during brainstorming)

- **Primary target:** Genius Lab JD; Niuro benefits from the AWS RDS + CI/CD overlap.
- **AWS:** real free-tier account (not LocalStack), with cost guards from day one.
- **Data source:** storeup.store (Nick's real Shopify store) via GraphQL Admin API. Test orders seeded because the store has no sales yet.
- **Pace:** MVP in 2–3 days, then iterate in phases. Webhooks, ODBC, Lambda, and Terraform are explicitly **post-MVP**.

## Repo

- Name: `ecommerce-data-warehouse` (public, github.com/internick2017)
- Local: `e:\dev\08-data\ecommerce-data-warehouse`
- Python 3.11+

```
ecommerce-data-warehouse/
├── extract/        # Shopify GraphQL connector (cursor pagination, rate-limit, retry/backoff)
├── load/           # S3 raw-JSON writer + Postgres raw loader (idempotent upserts)
├── transform/      # pure SQL: raw → staging → curated (star schema)
├── pipeline.py     # batch orchestrator: extract → load → transform, writes load_audit
├── seed_shopify.py # creates ~50–100 test orders spread over ~3 months via the API
├── infra/          # RDS/S3 setup notes + SQL; (phase 4: Terraform)
├── tests/          # pytest: mocked API, idempotency, data-quality checks
└── README.md       # architecture diagram, dashboard screenshots, design decisions
```

## Data flow (MVP)

```
Shopify GraphQL Admin API (storeup.store)
   │ paginated extract: orders, order line items, products, customers
   ▼
S3 bucket  raw/{entity}/{YYYY-MM-DD}/...json   (data-lake staging, 30-day lifecycle)
   ▼
Postgres on AWS RDS
   raw.*      one table per entity: JSONB payload + load_id + extracted_at
   staging.*  typed, deduplicated, normalized (SQL CTEs)
   curated.*  star schema: fact_orders, fact_order_items,
              dim_product, dim_customer, dim_date
   meta.load_audit   one row per run: rows extracted/loaded/rejected, duration, status
   raw.rejects       payloads that failed validation + reason
   ▼
Power BI Desktop → dashboard: revenue over time, top products, AOV, customer cohorts
```

### Key behaviors

- **Idempotent loads:** upsert by natural key (e.g., Shopify GID) + `load_id` lineage. Running the pipeline twice changes nothing. This is the JD's "data consistency controls."
- **Incremental extraction:** `updated_at` watermark per entity stored in `meta`; first run = full backfill, later runs = delta. (JD: "incremental loads/backfills".)
- **Rate-limit handling:** respect Shopify's cost-based throttle (GraphQL `throttleStatus`), exponential backoff with jitter on 429/5xx, bounded retries.
- **Validation:** pydantic models validate each payload before load; failures land in `raw.rejects` with a reason, never crash the run.
- **Transformations in SQL:** staging and curated layers are built with plain SQL files executed by the pipeline — CTEs and window functions on purpose (interview SQL refresher built into the work).

## AWS setup (free tier, cost-guarded)

Order matters — guards first:

1. **Billing alarm at $5** + budget, before creating any resource.
2. **S3 bucket** with lifecycle rule: expire `raw/` objects after 30 days.
3. **RDS Postgres** `db.t4g.micro`, single-AZ, 20 GB gp3, public access restricted to Nick's IP via security group. Stopped when not in use.
4. **IAM:** one programmatic user for the pipeline, least-privilege policy (that bucket only + nothing else; RDS reached via SQL credentials, not IAM).

## Testing

- **Unit (pytest):** pagination/parsing against recorded mock Shopify responses; retry/backoff logic; pydantic validation (valid, invalid, edge payloads).
- **Idempotency:** run loader twice against local Postgres (Docker) and assert identical row counts.
- **Data quality (post-transform, runs inside the pipeline too):** no orphan FKs in facts, fact totals reconcile with raw counts, no duplicate natural keys in dims. Failures mark the run `FAILED` in `load_audit`.

## Error handling summary

| Failure | Behavior |
|---|---|
| Shopify 429 / throttle | backoff + retry (bounded), then mark run failed |
| Invalid payload | row → `raw.rejects` with reason; run continues |
| S3/DB unreachable | fail fast, `load_audit` row with error, non-zero exit |
| Re-run after partial failure | safe: idempotent upserts + watermark not advanced on failure |

## Post-MVP roadmap (each phase = a new portfolio bullet)

- **Phase 2 — Webhooks:** FastAPI receiver for `orders/create` etc.: HMAC signature verification, idempotency keys, async enqueue → same loader. Exposed via cloudflared tunnel or Lambda function URL.
- **Phase 3 — ODBC/legacy:** SQL Server Express as a simulated legacy ERP (cost/inventory data); extraction via pyodbc with watermark-based incremental sync; enriches the star schema with real margin.
- **Phase 4 — Cloud-native:** pipeline on Lambda + EventBridge schedule; GitHub Actions CI/CD (tests on PR, deploy on merge); Terraform for S3/RDS/Lambda.

## Portfolio deliverable

- README in English: architecture diagram, dashboard screenshots, and a **Design Decisions** section (why 3 layers, why idempotency, why SQL-first transforms) — written for a technical founder to skim.
- Short case study on nickgranados.com once the MVP is live.

## Out of scope

- Real customer PII (test orders only; store has no sales).
- Orchestrators (Airflow/Prefect/dbt) — deliberately excluded; the JD asks for SQL, APIs, AWS, reliability.
- Redshift, multi-environment (dev/stage/prod) separation — may be discussed in README as "next steps."
