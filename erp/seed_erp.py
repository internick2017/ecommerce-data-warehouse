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
