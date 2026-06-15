# Phase 3 — Legacy ERP via ODBC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync per-SKU cost & on-hand inventory from a SQL Server "legacy ERP" over ODBC (pyodbc, watermark-incremental) into `raw.erp_costs`, then enrich the curated star schema with `line_cost`/`line_margin` and a `curated.dim_inventory`.

**Architecture:** A new self-contained `erp/` package (odbc connection-string builder, cursor-injected extractor, watermark sync reusing `meta.watermarks`) + a SQL Server service in docker-compose + a small change to `020_curated.sql`. pyodbc is mocked in all tests (cursor injection), so the build needs no ODBC driver; the real driver is only for the live demo.

**Tech Stack:** Python 3.11+, pyodbc (mocked in tests), psycopg 3 (reused), pytest, Docker (Postgres 16 :5433 + SQL Server 2022 :1433).

**Spec:** `docs/superpowers/specs/2026-06-13-erp-odbc-phase3-design.md`

**Environment notes for the implementer:**
- Windows 10, PowerShell. Python: `.venv\Scripts\python.exe`. Tests: `.venv\Scripts\python.exe -m pytest`.
- Repo root: `e:\dev\08-data\ecommerce-data-warehouse`. Paths below are relative to it.
- Postgres must be up: `docker compose up -d` (port 5433). **Do NOT start the mssql container during the build** — tests mock pyodbc; mssql is only for Nick's live demo.
- Reused modules (do not change behavior): `load.pg_loader.get_watermark(conn, entity)` /
  `set_watermark(conn, entity, ts)` (read/write `meta.watermarks`), `transform.runner.run_sql_files`.
- The `db` fixture (`tests/conftest.py`) is an autocommit psycopg connection that drops the
  raw/staging/curated/meta schemas before each test; tests bootstrap by running the SQL themselves.
- **Design decision (deviation from spec naming):** the `raw.erp_costs` table is created inside
  `transform/sql/001_schemas.sql` (not a separate `003_erp.sql`). Reason: every bootstrap path and
  test already runs `001`, so the table always exists before `020`'s LEFT JOIN — zero changes to
  `pipeline.py` or the other test files. The spec's intent (raw landing zone exists before curated
  joins it) is met.
- The order fixtures (`tests/fixtures.py`) produce line items with `sku = "SKU-1"`, `"SKU-2"`, etc.
  `seed_raw(db)` creates order 1 with `item(1, product1, qty=2, unit_price="15.00")` → `sku="SKU-1"`,
  `line_revenue = 30.00`.

---

### Task 1: pyodbc dep + SQL Server service + `raw.erp_costs` in bootstrap

**Files:**
- Modify: `requirements.txt`
- Modify: `docker-compose.yml`
- Modify: `transform/sql/001_schemas.sql`
- Create: `erp/__init__.py` (empty)
- Test: `tests/test_erp_sql.py`

- [ ] **Step 1: Add the dependency**

Append to `requirements.txt`:
```
pyodbc>=5.0
```
Run: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: pyodbc installs (the wheel installs without the ODBC driver; the driver is only needed at `connect()` time).

- [ ] **Step 2: Add the SQL Server service to `docker-compose.yml`**

Add a second service under `services:` (keep the existing `postgres` service unchanged):

```yaml
  mssql:
    image: mcr.microsoft.com/mssql/server:2022-latest
    environment:
      ACCEPT_EULA: "Y"
      MSSQL_SA_PASSWORD: "${MSSQL_SA_PASSWORD:-Dev_Str0ng_Pass!}"
    ports:
      - "1433:1433"
```

- [ ] **Step 3: Validate the compose file**

Run: `docker compose config`
Expected: prints the merged config with both `postgres` and `mssql` services, no error. (Do NOT `up` the mssql service.)

- [ ] **Step 4: Create empty `erp/__init__.py`**

- [ ] **Step 5: Write the failing test**

`tests/test_erp_sql.py`:

```python
from transform.runner import run_sql_files


def test_raw_erp_costs_table_created(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])
    cols = {
        r[0]
        for r in db.execute(
            "select column_name from information_schema.columns "
            "where table_schema='raw' and table_name='erp_costs'"
        ).fetchall()
    }
    assert {"sku", "unit_cost", "on_hand", "erp_updated_at", "loaded_at"} <= cols


def test_raw_erp_costs_upsert_by_sku(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])
    db.execute(
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())"
    )
    db.execute(
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 7.50, 90, now()) "
        "on conflict (sku) do update set unit_cost=excluded.unit_cost, on_hand=excluded.on_hand"
    )
    row = db.execute("select unit_cost, on_hand from raw.erp_costs where sku='SKU-1'").fetchone()
    assert row == (7.50, 90)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_sql.py -v`
Expected: FAIL — `raw.erp_costs` does not exist.

- [ ] **Step 7: Add `raw.erp_costs` to `transform/sql/001_schemas.sql`**

Insert this statement after the existing `raw.rejects` table block and before the `meta.load_audit`
block (it belongs with the other raw landing tables; one statement per `;`):

```sql
create table if not exists raw.erp_costs (
    sku            text primary key,
    unit_cost      numeric(12,2),
    on_hand        int,
    erp_updated_at timestamptz,
    loaded_at      timestamptz not null default now()
);
```

- [ ] **Step 8: Run tests to verify they pass + full suite (no regressions)**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_sql.py -v`  → 2 PASSED
Run: `.venv\Scripts\python.exe -m pytest -q`  → all pass (the existing `test_runner.py` subset
assertions still hold; `raw.erp_costs` is additive).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt docker-compose.yml transform/sql/001_schemas.sql erp/__init__.py tests/test_erp_sql.py
git commit -m "feat(erp): raw.erp_costs landing table + SQL Server service + pyodbc dep"
```

---

### Task 2: ODBC connection-string builder

**Files:**
- Create: `erp/odbc.py`
- Test: `tests/test_erp_odbc.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_erp_odbc.py`:

```python
from erp.odbc import build_conn_str


def test_build_conn_str_contains_all_parts():
    s = build_conn_str(
        server="localhost", port=1433, database="master",
        user="sa", password="P@ss",
    )
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in s
    assert "SERVER=localhost,1433" in s
    assert "DATABASE=master" in s
    assert "UID=sa" in s
    assert "PWD=P@ss" in s
    assert "Encrypt=yes" in s
    assert "TrustServerCertificate=yes" in s


def test_build_conn_str_custom_driver():
    s = build_conn_str(
        server="h", port=1433, database="d", user="u", password="p",
        driver="ODBC Driver 17 for SQL Server",
    )
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in s
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_odbc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'erp.odbc'`.

- [ ] **Step 3: Create `erp/odbc.py`**

```python
"""SQL Server ODBC connection helpers. build_conn_str is pure; connect() is the
only place that touches pyodbc (imported lazily so this module imports without
the driver present)."""

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"


def build_conn_str(server, port, database, user, password, driver=DEFAULT_DRIVER):
    """Build a SQL Server ODBC connection string.

    Encrypt=yes + TrustServerCertificate=yes accepts the dev container's
    self-signed cert (Driver 18 encrypts by default and would otherwise reject it).
    """
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes"
    )


def connect(conn_str):
    """Open a pyodbc connection. Requires the ODBC driver to be installed."""
    import pyodbc
    return pyodbc.connect(conn_str)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_odbc.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add erp/odbc.py tests/test_erp_odbc.py
git commit -m "feat(erp): ODBC connection-string builder + lazy connect"
```

---

### Task 3: Cost extractor (cursor-injected, incremental)

**Files:**
- Create: `erp/extractor.py`
- Test: `tests/test_erp_extractor.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_erp_extractor.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from erp.extractor import extract_costs


class FakeCursor:
    """Records execute() calls and returns canned rows. Mimics a pyodbc cursor."""

    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._rows


ROWS = [
    ("SKU-1", Decimal("8.25"), 10, datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ("SKU-2", Decimal("4.00"), 50, datetime(2026, 6, 2, tzinfo=timezone.utc)),
]


def test_full_extract_no_where_clause():
    cur = FakeCursor(ROWS)
    out = extract_costs(cur)
    sql, params = cur.executed[0]
    assert "where" not in sql.lower()
    assert params == ()
    assert out[0] == {"sku": "SKU-1", "unit_cost": Decimal("8.25"),
                      "on_hand": 10, "updated_at": datetime(2026, 6, 1, tzinfo=timezone.utc)}
    assert len(out) == 2


def test_incremental_extract_passes_watermark():
    cur = FakeCursor([ROWS[1]])
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = extract_costs(cur, updated_since=since)
    sql, params = cur.executed[0]
    assert "where updated_at > ?" in sql.lower()
    assert params == (since,)
    assert out == [{"sku": "SKU-2", "unit_cost": Decimal("4.00"),
                    "on_hand": 50, "updated_at": datetime(2026, 6, 2, tzinfo=timezone.utc)}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'erp.extractor'`.

- [ ] **Step 3: Create `erp/extractor.py`**

```python
"""SQL-based extraction of cost/inventory from the legacy ERP (dbo.product_costs).

The cursor is injected (a real pyodbc cursor in production, a fake in tests), so
this module has no pyodbc dependency and the SQL is fully testable.
"""

COLUMNS = ("sku", "unit_cost", "on_hand", "updated_at")
_BASE_SQL = "SELECT sku, unit_cost, on_hand, updated_at FROM dbo.product_costs"


def extract_costs(cursor, updated_since=None):
    """Return cost rows as dicts. With updated_since, only newer rows (incremental)."""
    if updated_since is None:
        cursor.execute(_BASE_SQL + " ORDER BY updated_at")
    else:
        cursor.execute(_BASE_SQL + " WHERE updated_at > ? ORDER BY updated_at", updated_since)
    return [dict(zip(COLUMNS, row)) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_extractor.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add erp/extractor.py tests/test_erp_extractor.py
git commit -m "feat(erp): cursor-injected cost extractor with incremental filter"
```

---

### Task 4: Watermark sync (ERP → raw.erp_costs)

**Files:**
- Create: `erp/sync.py`
- Test: `tests/test_erp_sync.py`

**Context:** `sync_costs` reads the `erp_costs` watermark from `meta.watermarks` (reusing
`load.pg_loader`), pulls the delta via `extract_costs`, upserts into `raw.erp_costs` by `sku`, and
advances the watermark. Tests use a fake ERP cursor + the real Postgres `db` fixture.

- [ ] **Step 1: Write the failing tests**

`tests/test_erp_sync.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from transform.runner import run_sql_files
from erp import sync
from load import pg_loader

T1 = datetime(2026, 6, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 2, tzinfo=timezone.utc)
T3 = datetime(2026, 6, 3, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._rows


def bootstrap(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])


def test_first_sync_lands_rows_and_sets_watermark(db):
    bootstrap(db)
    cur = FakeCursor([
        ("SKU-1", Decimal("8.25"), 10, T1),
        ("SKU-2", Decimal("4.00"), 50, T2),
    ])
    result = sync.sync_costs(db, cur)
    assert result["rows_synced"] == 2
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 2
    assert pg_loader.get_watermark(db, "erp_costs") == T2
    # first sync queried with no watermark
    assert cur.executed[0][1] == ()


def test_second_sync_uses_watermark_and_applies_delta(db):
    bootstrap(db)
    sync.sync_costs(db, FakeCursor([
        ("SKU-1", Decimal("8.25"), 10, T1),
        ("SKU-2", Decimal("4.00"), 50, T2),
    ]))
    # a later cost change for SKU-1 at T3 (the real SQL Server would filter by watermark;
    # the fake returns only the delta row)
    cur2 = FakeCursor([("SKU-1", Decimal("9.00"), 8, T3)])
    result = sync.sync_costs(db, cur2)
    assert result["rows_synced"] == 1
    # proves it queried with the stored watermark (T2)
    assert cur2.executed[0][1] == (T2,)
    row = db.execute("select unit_cost, on_hand from raw.erp_costs where sku='SKU-1'").fetchone()
    assert row == (Decimal("9.00"), 8)
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 2  # still 2 skus
    assert pg_loader.get_watermark(db, "erp_costs") == T3


def test_resync_same_data_is_idempotent(db):
    bootstrap(db)
    rows = [("SKU-1", Decimal("8.25"), 10, T1)]
    sync.sync_costs(db, FakeCursor(rows))
    sync.sync_costs(db, FakeCursor(rows))
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 1


def test_empty_sync_keeps_watermark(db):
    bootstrap(db)
    result = sync.sync_costs(db, FakeCursor([]))
    assert result["rows_synced"] == 0
    assert pg_loader.get_watermark(db, "erp_costs") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'erp.sync'`.

- [ ] **Step 3: Create `erp/sync.py`**

```python
"""Incremental ERP cost/inventory sync into raw.erp_costs (watermark-driven)."""
from erp.extractor import extract_costs
from load import pg_loader

ENTITY = "erp_costs"

_UPSERT = """
insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at)
values (%s, %s, %s, %s)
on conflict (sku) do update set
    unit_cost = excluded.unit_cost,
    on_hand = excluded.on_hand,
    erp_updated_at = excluded.erp_updated_at,
    loaded_at = now()
"""


def sync_costs(pg_conn, erp_cursor):
    """Pull cost rows changed since the watermark, upsert into raw.erp_costs,
    advance the watermark. Returns {'rows_synced', 'new_watermark'}."""
    since = pg_loader.get_watermark(pg_conn, ENTITY)
    rows = extract_costs(erp_cursor, updated_since=since)

    max_updated = since
    for r in rows:
        pg_conn.execute(_UPSERT, (r["sku"], r["unit_cost"], r["on_hand"], r["updated_at"]))
        ts = r["updated_at"]
        if max_updated is None or ts > max_updated:
            max_updated = ts

    if rows and max_updated is not None:
        pg_loader.set_watermark(pg_conn, ENTITY, max_updated)

    return {"rows_synced": len(rows), "new_watermark": max_updated}
```

- [ ] **Step 4: Run tests to verify they pass + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_sync.py -v`  → 4 PASSED
Run: `.venv\Scripts\python.exe -m pytest -q`  → all pass

- [ ] **Step 5: Commit**

```bash
git add erp/sync.py tests/test_erp_sync.py
git commit -m "feat(erp): watermark-incremental cost sync into raw.erp_costs"
```

---

### Task 5: Curated margin + inventory dimension

**Files:**
- Modify: `transform/sql/020_curated.sql`
- Test: `tests/test_curated_margin.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_curated_margin.py`:

```python
from decimal import Decimal

from tests.fixtures import seed_raw
from transform.runner import run_sql_files

BOOTSTRAP = ["transform/sql/001_schemas.sql"]
TRANSFORMS = ["transform/sql/010_staging.sql", "transform/sql/020_curated.sql"]


def build_with_costs(db, costs_sql=None):
    run_sql_files(db, BOOTSTRAP)
    seed_raw(db)
    if costs_sql:
        db.execute(costs_sql)
    run_sql_files(db, TRANSFORMS)


def test_margin_computed_when_cost_present(db):
    # fixture order 1: SKU-1, quantity 2 @ unit_price 15.00 -> line_revenue 30.00
    build_with_costs(
        db,
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())",
    )
    row = db.execute(
        "select unit_cost, line_cost, line_margin from curated.fact_order_items "
        "where sku='SKU-1'"
    ).fetchone()
    assert row[0] == Decimal("6.00")    # unit_cost
    assert row[1] == Decimal("12.00")   # line_cost = 2 * 6.00
    assert row[2] == Decimal("18.00")   # line_margin = 30.00 - 12.00


def test_margin_null_when_no_cost(db):
    build_with_costs(db)  # no erp_costs seeded
    row = db.execute(
        "select unit_cost, line_cost, line_margin from curated.fact_order_items where sku='SKU-2'"
    ).fetchone()
    assert row == (None, None, None)


def test_dim_inventory_built(db):
    build_with_costs(
        db,
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())",
    )
    row = db.execute(
        "select on_hand, unit_cost from curated.dim_inventory where sku='SKU-1'"
    ).fetchone()
    assert row == (100, Decimal("6.00"))


def test_existing_curated_still_builds(db):
    # revenue column untouched by the margin change
    build_with_costs(db)
    total = db.execute("select sum(line_revenue) from curated.fact_order_items").fetchone()[0]
    assert total == Decimal("65.00")  # same as the MVP curated test
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_curated_margin.py -v`
Expected: FAIL — `fact_order_items` has no `unit_cost`/`line_cost`/`line_margin`; `curated.dim_inventory` doesn't exist.

- [ ] **Step 3: Modify `transform/sql/020_curated.sql`**

(a) In the top drop block, add a drop for the new dimension. Change:

```sql
drop table if exists curated.fact_order_items cascade;
drop table if exists curated.fact_orders cascade;
drop table if exists curated.dim_product cascade;
drop table if exists curated.dim_customer cascade;
drop table if exists curated.dim_date cascade;
```
to:
```sql
drop table if exists curated.fact_order_items cascade;
drop table if exists curated.fact_orders cascade;
drop table if exists curated.dim_inventory cascade;
drop table if exists curated.dim_product cascade;
drop table if exists curated.dim_customer cascade;
drop table if exists curated.dim_date cascade;
```

(b) Replace the `fact_order_items` create statement. Change:

```sql
create table curated.fact_order_items as
select
    i.line_item_gid,
    i.order_gid,
    p.product_key,
    i.title,
    i.sku,
    i.quantity,
    i.unit_price,
    (i.quantity * i.unit_price)::numeric(12,2) as line_revenue
from staging.order_items i
left join curated.dim_product p using (product_gid);
```
to (LEFT JOIN raw.erp_costs by sku → cost & margin; NULL when no cost row):
```sql
create table curated.fact_order_items as
select
    i.line_item_gid,
    i.order_gid,
    p.product_key,
    i.title,
    i.sku,
    i.quantity,
    i.unit_price,
    (i.quantity * i.unit_price)::numeric(12,2)                          as line_revenue,
    ec.unit_cost,
    (i.quantity * ec.unit_cost)::numeric(12,2)                          as line_cost,
    ((i.quantity * i.unit_price) - (i.quantity * ec.unit_cost))::numeric(12,2) as line_margin
from staging.order_items i
left join curated.dim_product p using (product_gid)
left join raw.erp_costs ec on ec.sku = i.sku;
```

(c) Add the inventory dimension. Insert this immediately AFTER the `fact_order_items` index
statements (after the `create index fact_order_items_order_gid_idx ...;` line at the end of the file):

```sql
create table curated.dim_inventory as
select sku, on_hand, unit_cost
from raw.erp_costs;

alter table curated.dim_inventory add primary key (sku);
```

- [ ] **Step 4: Run tests to verify they pass + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_curated_margin.py -v`  → 4 PASSED
Run: `.venv\Scripts\python.exe -m pytest -q`  → all pass (existing `test_curated.py`,
`test_quality.py`, and the webhook end-to-end test still build curated; the new columns are
additive and the quality reconciliation only sums `line_revenue`, which is unchanged).

- [ ] **Step 5: Commit**

```bash
git add transform/sql/020_curated.sql tests/test_curated_margin.py
git commit -m "feat(curated): line_cost/line_margin on fact_order_items + dim_inventory"
```

---

### Task 6: ERP seeder + sync entrypoint + config

**Files:**
- Create: `erp/seed_erp.py`
- Create: `run_erp_sync.py`
- Modify: `.env.example`
- Test: `tests/test_erp_seed.py`

- [ ] **Step 1: Write the failing test (pure cost-row builder)**

`tests/test_erp_seed.py`:

```python
import random
from decimal import Decimal

from erp.seed_erp import cost_rows_from_skus


def test_cost_rows_from_skus_deterministic_and_priced():
    pairs = [("SKU-1", Decimal("15.00")), ("SKU-2", Decimal("20.00"))]
    rng = random.Random(42)
    rows = cost_rows_from_skus(pairs, rng, cost_ratio=0.55)
    assert [r[0] for r in rows] == ["SKU-1", "SKU-2"]
    # unit_cost = round(price * 0.55, 2)
    assert rows[0][1] == Decimal("8.25")
    assert rows[1][1] == Decimal("11.00")
    # on_hand is a non-negative int
    assert all(isinstance(r[2], int) and r[2] >= 0 for r in rows)
    # deterministic for the same seed
    assert cost_rows_from_skus(pairs, random.Random(42), cost_ratio=0.55) == rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'erp.seed_erp'`.

- [ ] **Step 3: Create `erp/seed_erp.py`**

```python
"""Seed the legacy ERP (SQL Server dbo.product_costs) with realistic per-SKU costs.

Reads the distinct SKUs + average unit price from the warehouse (staging.order_items),
computes a plausible cost (~55% of price) and a random on-hand, and upserts them into
SQL Server. The cost-row builder is pure (seedable RNG) and unit-tested; the live wiring
needs the ODBC driver + a running SQL Server.

Usage: python erp/seed_erp.py [--seed N] [--cost-ratio 0.55]
"""
import argparse
from decimal import Decimal, ROUND_HALF_UP


def cost_rows_from_skus(sku_price_pairs, rng, cost_ratio=0.55):
    """[(sku, avg_price)] -> [(sku, unit_cost, on_hand)]. Pure; rng is injected."""
    rows = []
    for sku, avg_price in sku_price_pairs:
        unit_cost = (Decimal(avg_price) * Decimal(str(cost_ratio))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        on_hand = rng.randint(0, 500)
        rows.append((sku, unit_cost, on_hand))
    return rows


def _distinct_sku_prices(pg_conn):
    return [
        (r[0], r[1])
        for r in pg_conn.execute(
            "select sku, avg(unit_price) from staging.order_items "
            "where sku is not null group by sku order by sku"
        ).fetchall()
    ]


_CREATE_TABLE = """
IF OBJECT_ID('dbo.product_costs', 'U') IS NULL
CREATE TABLE dbo.product_costs (
    sku        NVARCHAR(100) PRIMARY KEY,
    unit_cost  DECIMAL(12,2) NOT NULL,
    on_hand    INT NOT NULL,
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
)
"""

_MERGE = """
MERGE dbo.product_costs AS t
USING (SELECT ? AS sku, ? AS unit_cost, ? AS on_hand) AS s
ON t.sku = s.sku
WHEN MATCHED THEN UPDATE SET unit_cost = s.unit_cost, on_hand = s.on_hand, updated_at = SYSUTCDATETIME()
WHEN NOT MATCHED THEN INSERT (sku, unit_cost, on_hand) VALUES (s.sku, s.unit_cost, s.on_hand);
"""


def main():
    import os
    import random

    from dotenv import load_dotenv

    from erp import odbc
    from load import pg_loader

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--cost-ratio", type=float, default=0.55)
    args = parser.parse_args()

    load_dotenv()
    pg = pg_loader.connect()
    pairs = _distinct_sku_prices(pg)
    if not pairs:
        raise SystemExit("No SKUs in staging.order_items — run the pipeline first.")
    rows = cost_rows_from_skus(pairs, random.Random(args.seed), cost_ratio=args.cost_ratio)

    conn = odbc.connect(odbc.build_conn_str(
        server=os.environ.get("MSSQL_HOST", "localhost"),
        port=int(os.environ.get("MSSQL_PORT", "1433")),
        database=os.environ.get("MSSQL_DB", "master"),
        user=os.environ.get("MSSQL_USER", "sa"),
        password=os.environ["MSSQL_SA_PASSWORD"],
        driver=os.environ.get("MSSQL_ODBC_DRIVER", odbc.DEFAULT_DRIVER),
    ))
    cur = conn.cursor()
    cur.execute(_CREATE_TABLE)
    for sku, unit_cost, on_hand in rows:
        cur.execute(_MERGE, sku, unit_cost, on_hand)
    conn.commit()
    print(f"seeded {len(rows)} product_costs rows into SQL Server")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_erp_seed.py -v`
Expected: 1 PASSED.

- [ ] **Step 5: Create `run_erp_sync.py` (repo root)**

```python
"""Run one incremental ERP cost/inventory sync (pyodbc -> raw.erp_costs).

Needs the ODBC Driver 18 installed and the SQL Server container running
(docker compose up -d mssql). Refresh the curated margin afterwards with:
    python pipeline.py
"""
import os

from dotenv import load_dotenv

from erp import odbc, sync
from load import pg_loader
from transform.runner import run_sql_files


def main():
    load_dotenv()
    pg = pg_loader.connect()
    run_sql_files(pg, ["transform/sql/001_schemas.sql"])  # ensure raw.erp_costs exists

    erp_conn = odbc.connect(odbc.build_conn_str(
        server=os.environ.get("MSSQL_HOST", "localhost"),
        port=int(os.environ.get("MSSQL_PORT", "1433")),
        database=os.environ.get("MSSQL_DB", "master"),
        user=os.environ.get("MSSQL_USER", "sa"),
        password=os.environ["MSSQL_SA_PASSWORD"],
        driver=os.environ.get("MSSQL_ODBC_DRIVER", odbc.DEFAULT_DRIVER),
    ))
    result = sync.sync_costs(pg, erp_conn.cursor())
    print(f"ERP sync: rows_synced={result['rows_synced']} "
          f"watermark={result['new_watermark']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Update `.env.example`**

Append after the existing content:

```ini

# Legacy ERP (SQL Server via ODBC) — Phase 3. The mssql docker service reads
# MSSQL_SA_PASSWORD (8+ chars, upper/lower/digit/symbol). Install "ODBC Driver 18
# for SQL Server" for the live sync.
MSSQL_HOST=localhost
MSSQL_PORT=1433
MSSQL_DB=master
MSSQL_USER=sa
MSSQL_SA_PASSWORD=Dev_Str0ng_Pass!
MSSQL_ODBC_DRIVER=ODBC Driver 18 for SQL Server
```

- [ ] **Step 7: Syntax-check the entrypoints (no DB/driver needed) + full suite**

Run: `.venv\Scripts\python.exe -c "import ast; ast.parse(open('run_erp_sync.py').read()); ast.parse(open('erp/seed_erp.py').read()); print('syntax OK')"`
Expected: `syntax OK`. (Do NOT execute them — they connect to SQL Server.)
Run: `.venv\Scripts\python.exe -m pytest -q`  → all pass.

- [ ] **Step 8: Commit**

```bash
git add erp/seed_erp.py run_erp_sync.py .env.example tests/test_erp_seed.py
git commit -m "feat(erp): SQL Server seeder + sync entrypoint + config"
```

---

### Task 7: Live demo + README

No new app code; wires the sync to a real SQL Server and documents the phase.

- [ ] **Step 1 (manual, Nick): install the ODBC driver + start SQL Server**

Install **Microsoft ODBC Driver 18 for SQL Server** (MSI from Microsoft, run as admin). Then:
```powershell
docker compose up -d mssql           # wait ~30s for SQL Server to accept connections
```
Ensure `MSSQL_SA_PASSWORD` in `.env` matches the value docker-compose used (the default
`Dev_Str0ng_Pass!` works for both since compose reads the same env).

- [ ] **Step 2 (manual, Nick): seed + sync + refresh**

```powershell
.venv\Scripts\python.exe erp\seed_erp.py --seed 42   # costs from the store's SKUs
.venv\Scripts\python.exe run_erp_sync.py             # incremental pyodbc sync
.venv\Scripts\python.exe pipeline.py                 # rebuild curated -> margin + inventory
```
Verify:
```powershell
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); from load import pg_loader; c=pg_loader.connect(); print(c.execute('select count(*) costed, sum(line_margin) margin from curated.fact_order_items where line_margin is not null').fetchall())"
```
Then change one cost in SQL Server and re-run `run_erp_sync.py` to show the watermark pulling only
the changed row. Capture the output for the README.

- [ ] **Step 2b (optional, Nick): point Power BI at `curated.dim_inventory` + `fact_order_items`**
to add a margin-% card and an on-hand-by-product bar. Screenshot for the case study.

- [ ] **Step 3: Update `README.md`**

Add the ERP source to the architecture mermaid diagram (a `SQL Server (legacy ERP)` node → an
`ERP sync (pyodbc)` node feeding the RDS raw store), and add this section after the Phase 2 section:

```markdown
## Phase 3 — Legacy ERP via ODBC (cost & margin)

A second source system — a SQL Server "legacy ERP" — supplies per-SKU **unit cost** and
**on-hand inventory**, reached over **ODBC** (`erp/`):

- **ODBC connectivity** — pyodbc + the Microsoft ODBC Driver 18; connection string built in
  `erp/odbc.py` (`Encrypt=yes` with the dev container's self-signed cert).
- **Incremental sync** — `erp/sync.py` pulls only rows changed since the `erp_costs` watermark
  (`SELECT ... WHERE updated_at > ?`), upserts them into `raw.erp_costs` by SKU, and advances the
  watermark — reusing the same `meta.watermarks` mechanism as the Shopify extractor.
- **Margin enrichment** — the curated rebuild LEFT JOINs `raw.erp_costs` onto `fact_order_items`
  for `line_cost` and `line_margin`, and builds a `curated.dim_inventory`. SKUs without ERP cost
  get NULL margin (the batch path is unaffected when the ERP isn't synced).

SQL Server runs as a Docker service; `erp/seed_erp.py` seeds realistic costs from the store's own
SKUs, then `python run_erp_sync.py` performs the incremental ODBC sync.
```

Also update the Testing count and the Project layout (`erp/` package, `run_erp_sync.py`), and
remove the ODBC item from the Roadmap.

- [ ] **Step 4: Final test sweep + commit**

Run: `.venv\Scripts\python.exe -m pytest -q`  → all pass.
```bash
git add README.md
git commit -m "docs: document Phase 3 legacy ERP via ODBC"
```

---

## Self-review notes

- **Spec coverage:** docker mssql service + pyodbc dep (Task 1); `raw.erp_costs` landing (Task 1,
  in `001` not a separate `003` — documented deviation, same effect); `build_conn_str`/`connect`
  (Task 2); cursor-injected incremental extractor (Task 3); watermark sync reusing `meta.watermarks`
  (Task 4); `line_cost`/`line_margin` + `dim_inventory` (Task 5); seeder + entrypoint + config
  (Task 6); live demo + README (Task 7). Error-handling table: incremental/idempotent covered by
  Task 4 tests; NULL-margin-without-cost by Task 5; ODBC-failure is the live `connect()` raising
  (manual). Testing matrix: Tasks 2–5. pyodbc is mocked throughout — no driver needed to build.
- **Reuse:** `pg_loader.get_watermark`/`set_watermark`, `run_sql_files` used with real signatures;
  `meta.watermarks` reused for the `erp_costs` entity; no change to the Shopify batch logic.
- **Type consistency:** `extract_costs(cursor, updated_since)` returns dicts with keys
  `sku/unit_cost/on_hand/updated_at`; `sync_costs` reads those exact keys; `raw.erp_costs` columns
  `sku/unit_cost/on_hand/erp_updated_at` map from them in the upsert. `build_conn_str` params match
  the callers in `seed_erp.py`/`run_erp_sync.py`.

## Execution order & estimate

- Tasks 1–6 are codeable + testable locally with **no ODBC driver** (~1.5–2h with reviews).
- Task 7 has Nick's manual steps (install driver, start mssql, seed/sync, Power BI); the README can
  be written from the design before the live capture.

## Out of scope (per spec)

Multi-table ERP, large-dataset fetch tuning, cloud hosting/scheduling of the sync (Phase 4).
