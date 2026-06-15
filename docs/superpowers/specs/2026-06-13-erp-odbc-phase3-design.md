# Phase 3 — Legacy ERP via ODBC (cost & inventory → margin) — Design Spec

**Date:** 2026-06-13
**Author:** Nick Granados (with Claude)
**Status:** Approved
**Builds on:** the MVP + Phase 2 (webhooks), both on `master`.

## Purpose

Integrate a simulated **legacy ERP** running on **SQL Server** as a second source system,
reached over **ODBC** (pyodbc + Microsoft ODBC Driver 18). It supplies per-SKU **unit cost** and
**on-hand inventory**, synced **incrementally by watermark** into the warehouse, which then
enriches the star schema with real **margin** (revenue − cost) and an inventory dimension.

This phase exists to demonstrate the JD's **"ODBC & Legacy System Connectivity (Strong): ODBC
driver configuration, SQL-based extraction from ERPs/CRMs, handling large datasets, incremental
sync strategies."**

**Success criteria:** an incremental pyodbc sync lands `dbo.product_costs` rows into
`raw.erp_costs` (Postgres), advances the `erp_costs` watermark, and re-running pulls only deltas
and is idempotent; the curated rebuild then exposes `line_cost` / `line_margin` on
`fact_order_items` and a `curated.dim_inventory`. Demonstrated end-to-end once against a real SQL
Server (Docker) after the ODBC driver is installed.

## Scope decisions (from brainstorming)

- **One sub-project.** Phase 4 (cloud-native) is a separate spec.
- **ERP data:** a single `dbo.product_costs` table keyed by SKU — `unit_cost`, `on_hand`,
  `updated_at`. One table keeps the incremental-sync demo clean while covering both the margin
  (cost) and inventory (on-hand) angles.
- **Enrichment lands on the existing star schema:** `020_curated.sql`'s `fact_order_items` is
  extended (LEFT JOIN `raw.erp_costs` by SKU) with `unit_cost`, `line_cost`, `line_margin`; a new
  `curated.dim_inventory` carries `on_hand` + `unit_cost` per SKU. LEFT JOIN means margin is NULL
  until the ERP is synced — the batch path keeps working with or without the ERP.
- **Driver/SQL Server are real, tests are mocked.** pyodbc is mocked in unit/integration tests
  (no driver needed to build), exactly like Phase 2's approach; the real pyodbc → SQL Server path
  is the live demo, gated on Nick installing the ODBC driver (which *is* the JD's "ODBC driver
  configuration").

## Manual prerequisites (Nick)

1. **Install Microsoft ODBC Driver 18 for SQL Server** (MSI from Microsoft, run as admin). Required
   only for the live sync; the build + tests do not need it.
2. Set a strong `MSSQL_SA_PASSWORD` in `.env` (SQL Server requires 8+ chars with complexity). A
   default is provided in `.env.example`.

The SQL Server container and its seed are handled by the build (Docker is already running).

## Architecture

A new `erp/` package connects to SQL Server over ODBC, extracts cost/inventory rows incrementally,
and lands them in a new raw layer the curated SQL already knows how to join.

```
SQL Server  dbo.product_costs (sku PK, unit_cost, on_hand, updated_at)   [legacy ERP, Docker :1433]
   |  pyodbc:  SELECT ... WHERE updated_at > ?   (watermark; first run = full)
   v
 erp/sync.py  -> upsert raw.erp_costs (Postgres, by sku) + advance meta.watermarks['erp_costs']
   v
 020_curated.sql  fact_order_items LEFT JOIN raw.erp_costs ON sku:
     unit_cost, line_cost = unit_cost*quantity, line_margin = line_revenue - line_cost
   + curated.dim_inventory (sku, on_hand, unit_cost)
   v
 Power BI:  margin %, margin by product, on-hand inventory
```

## Components

### `docker-compose.yml` (modify)
Add an `mssql` service: `mcr.microsoft.com/mssql/server:2022-latest`, `ACCEPT_EULA=Y`,
`MSSQL_SA_PASSWORD` from env, port `1433:1433`. The existing `postgres` service is unchanged.

### `erp/odbc.py`
- `build_conn_str(server, port, database, user, password, driver="ODBC Driver 18 for SQL Server") -> str`
  — pure function building the ODBC connection string (includes `Encrypt=yes;TrustServerCertificate=yes`
  for the self-signed dev container). Unit-testable without a driver.
- `connect(conn_str)` — thin `pyodbc.connect(conn_str)` wrapper (imported lazily so the module
  imports without the driver present).

### `erp/extractor.py`
- `extract_costs(cursor, updated_since=None) -> list[dict]` — executes
  `SELECT sku, unit_cost, on_hand, updated_at FROM dbo.product_costs [WHERE updated_at > ?] ORDER BY updated_at`,
  returns a list of row dicts. Cursor is injected (a real pyodbc cursor live; a fake cursor in
  tests). The `updated_since` param drives incremental extraction.

### `erp/sync.py`
- `sync_costs(pg_conn, erp_cursor) -> dict` — reads the `erp_costs` watermark from `meta.watermarks`
  (reusing `load.pg_loader.get_watermark`/`set_watermark`), extracts rows since it, upserts them
  into `raw.erp_costs` by `sku`, advances the watermark to the max `updated_at` seen, and returns a
  summary (`rows_synced`, `new_watermark`). Re-running pulls only deltas; the upsert is idempotent.

### `erp/seed_erp.py`
- Reads distinct SKUs and average unit price from `staging.order_items` (Postgres), computes a
  plausible cost (~55% of avg price) and a random `on_hand`, and **upserts** them into the SQL
  Server `dbo.product_costs` (creating the table if absent). One-shot, live. Produces realistic
  margins against the real order data. The cost/on_hand RNG is seedable for reproducibility.

### SQL
- `transform/sql/003_erp.sql` — `create table if not exists raw.erp_costs (sku text primary key,
  unit_cost numeric(12,2), on_hand int, erp_updated_at timestamptz, loaded_at timestamptz default now())`.
  Added to the bootstrap sequence so `raw.erp_costs` always exists (empty until synced).
- `transform/sql/020_curated.sql` (modify) — `fact_order_items` gains `unit_cost`, `line_cost`
  (`unit_cost * quantity`), `line_margin` (`line_revenue - line_cost`) via `LEFT JOIN raw.erp_costs
  USING (sku)`; add `curated.dim_inventory (sku, on_hand, unit_cost)` from `raw.erp_costs`.

### `run_erp_sync.py`
- Entrypoint: `load_dotenv`, connect Postgres (`pg_loader.connect`) + SQL Server
  (`erp.odbc.build_conn_str` + `connect` from env), bootstrap `001` + `003`, run `sync_costs`,
  print the summary. The curated margin refreshes on the next `python pipeline.py`.

### Config
Add to `.env.example`:
- `MSSQL_HOST=localhost`, `MSSQL_PORT=1433`, `MSSQL_DB=master`, `MSSQL_USER=sa`,
  `MSSQL_SA_PASSWORD=` (with a complexity note), `MSSQL_ODBC_DRIVER=ODBC Driver 18 for SQL Server`.

New dependency in `requirements.txt`: `pyodbc>=5.0`.

## Data flow & incremental semantics

- **Watermark:** `meta.watermarks['erp_costs']` holds the last `updated_at` synced. First run
  (no watermark) = full pull; subsequent runs pull `updated_at > watermark`. The SQL Server seed
  sets `updated_at = sysutcdatetime()` and bumps it on cost changes, so editing a cost and
  re-syncing pulls only that row — the incremental-sync demo.
- **Idempotency:** `raw.erp_costs` upsert is keyed by `sku` (last write wins); re-running a sync
  changes nothing if no ERP rows changed.
- **Margin via LEFT JOIN:** a SKU in orders with no ERP cost yields NULL `unit_cost`/`line_margin`
  — honest (not every SKU has cost data) and non-breaking.

## Error handling

| Condition | Behavior |
|---|---|
| ODBC driver missing / SQL Server down | `connect()` raises a clear pyodbc error; the sync fails loudly (no partial state — watermark not advanced) |
| SKU without ERP cost | LEFT JOIN → NULL cost/margin; batch path unaffected |
| Re-sync with no ERP changes | delta is empty; watermark unchanged; no-op |
| Negative/zero cost (clearance) | allowed; `line_margin` may be negative (real) |

## Testing

`tests/` (pytest), reusing the Postgres `db` fixture. **pyodbc is mocked — no driver needed.**

- **`erp/odbc.py`:** `build_conn_str(...)` produces the expected ODBC string (driver, server,port,
  database, uid/pwd, Encrypt/TrustServerCertificate).
- **`erp/extractor.py`:** `extract_costs(fake_cursor)` issues the full-scan SQL with no params;
  `extract_costs(fake_cursor, updated_since=ts)` issues the `WHERE updated_at > ?` SQL with the ts
  param; both map cursor rows → dicts. The fake cursor records `execute(sql, params)` and returns
  canned rows.
- **`erp/sync.py` (fake ERP cursor + real Postgres):** first sync (no watermark) lands all rows
  into `raw.erp_costs` and sets the watermark to max updated_at; a second sync with a later cursor
  pulls only the newer row (delta); re-running the same data is idempotent (row count stable).
- **SQL margin (`003` + `020`):** seed `raw.erp_costs` + the existing order fixtures, run the
  curated build, assert `fact_order_items.line_cost`/`line_margin` compute correctly and a SKU
  without a cost row has NULL margin; assert `curated.dim_inventory` carries `on_hand`.
- Existing `test_curated.py` build sequences gain `003_erp.sql` so `raw.erp_costs` exists; existing
  assertions still pass (new columns are additive, costs NULL when unseeded).

## Live demo (manual, once — after the ODBC driver is installed)

```powershell
docker compose up -d mssql                 # SQL Server in Docker (handled by the build)
.venv\Scripts\python.exe erp\seed_erp.py   # seed costs/inventory from the store's SKUs
.venv\Scripts\python.exe run_erp_sync.py   # incremental pyodbc sync -> raw.erp_costs
.venv\Scripts\python.exe pipeline.py       # rebuild curated -> margin + inventory
```
Then edit one cost in SQL Server and re-run `run_erp_sync.py` to show the watermark pulling only
the changed row. Capture the output for the README.

## Deliverable updates

- README: add the ERP/ODBC source to the architecture diagram and a "Phase 3 — Legacy ERP via
  ODBC" section (driver config, incremental watermark sync, margin enrichment). Move the ODBC item
  out of the Roadmap.
- The GitHub repo gains the `erp/` package, new SQL, and tests — the JD's ODBC bullet, demonstrated.

## Out of scope (this phase)

- Multi-table ERP (suppliers, purchase orders) — one cost/inventory table is enough for the bullet.
- Real large-dataset volume tuning (batched fetches) — note the `fetchmany` pattern in the README
  as the scaling path, but the seed volume is small.
- Cloud hosting / scheduling of the sync — Phase 4.
